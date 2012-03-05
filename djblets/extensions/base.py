#
# base.py -- Base classes for extensions.
#
# Copyright (c) 2010-2011  Beanbag, Inc.
# Copyright (c) 2008-2010  Christian Hammond
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import logging
import os
import pkg_resources
import shutil
import sys

from django.conf import settings
from django.conf.urls.defaults import patterns, include
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.urlresolvers import get_resolver, get_mod_func
from django.db.models import loading

from django_evolution.management.commands.evolve import Command as Evolution

from djblets.extensions.errors import DisablingExtensionError, \
                                      EnablingExtensionError, \
                                      InstallExtensionError, \
                                      InvalidExtensionError
from djblets.extensions.models import RegisteredExtension
from djblets.extensions.signals import extension_initialized, \
                                       extension_uninitialized



if not hasattr(settings, "EXTENSIONS_STATIC_ROOT"):
    raise ImproperlyConfigured, \
          "settings.EXTENSIONS_STATIC_ROOT must be defined"


_extension_managers = []


class Settings(dict):
    """
    Settings data for an extension. This is a glorified dictionary that
    acts as a proxy for the extension's stored settings in the database.

    Callers must call save() when they want to make the settings persistent.
    """
    def __init__(self, extension):
        dict.__init__(self)
        self.extension = extension
        self.load()

    def load(self):
        """Loads the settings from the database."""
        try:
            self.update(self.extension.registration.settings)
        except ValueError:
            # The settings in the database are invalid. We'll have to discard
            # it. Note that this should never happen unless the user
            # hand-modifies the entries and breaks something.
            pass

    def save(self):
        """Saves all current settings to the database."""
        registration = self.extension.registration
        registration.settings = dict(self)
        registration.save()


class Extension(object):
    """Base class for an extension.

    Extensions must subclass for this class. They'll automatically have
    support for settings, adding hooks, and plugging into the administration
    UI.

    If an extension supports configuration in the UI, it should set
    :py:attr:`is_configurable` to True.

    Extensions should list all other extension names that they require in
    :py:attr:`requirements`.
    """
    is_configurable = False
    requirements = []
    resources = []

    def __init__(self):
        self.hooks = set()
        self.admin_ext_resolver = None
        self.settings = Settings(self)

    def shutdown(self):
        """Shuts down the extension.

        This will shut down every registered hook.

        Subclasses should override this if they need custom shutdown behavior.
        """
        for hook in self.hooks:
            hook.shutdown()

    def _get_admin_urlconf(self):
        if not hasattr(self, "_admin_urlconf_module"):
            try:
                name = "%s.%s" % (get_mod_func(self.__class__.__module__)[0],
                                  "admin_urls")
                self._admin_urlconf_module = __import__(name, {}, {}, [''])
            except Exception, e:
                raise ImproperlyConfigured, \
                    "Error while importing extension's admin URLconf %r: %s" % \
                    (name, e)

        return self._admin_urlconf_module
    admin_urlconf = property(_get_admin_urlconf)


class ExtensionInfo(object):
    """Information on an extension.

    This class stores the information and metadata on an extension. This
    includes the name, version, author information, where it can be downloaded,
    whether or not it's enabled or installed, and anything else that may be
    in the Python package for the extension.
    """
    def __init__(self, entrypoint, ext_class):
        metadata = {}

        for line in entrypoint.dist.get_metadata_lines("PKG-INFO"):
            key, value = line.split(": ", 1)

            if value != "UNKNOWN":
                metadata[key] = value

        self.metadata = metadata
        self.name = entrypoint.dist.project_name
        self.version = entrypoint.dist.version
        self.summary = metadata.get('Summary')
        self.description = metadata.get('Description')
        self.author = metadata.get('Author')
        self.author_email = metadata.get('Author-email')
        self.license = metadata.get('License')
        self.url = metadata.get('Home-page')
        self.app_name = '.'.join(ext_class.__module__.split('.')[:-1])
        self.enabled = False
        self.installed = False
        self.is_configurable = ext_class.is_configurable
        self.htdocs_path = os.path.join(settings.EXTENSIONS_STATIC_ROOT,
                                        self.name)

    def __unicode__(self):
        return "%s %s (enabled = %s)" % (self.name, self.version, self.enabled)


class ExtensionHook(object):
    """The base class for a hook into some part of the project.

    ExtensionHooks are classes that can hook into an
    :py:class:`ExtensionHookPoint` to provide some level of functionality
    in a project. A project should provide a subclass of ExtensionHook that
    will provide functions for getting data or anything else that's needed,
    and then extensions will subclass that specific ExtensionHook.

    A base ExtensionHook subclass must use :py:class:`ExtensionHookPoint`
    as a metaclass. For example::

        class NavigationHook(ExtensionHook):
            __metaclass__ = ExtensionHookPoint
    """
    def __init__(self, extension):
        self.extension = extension
        self.extension.hooks.add(self)
        self.__class__.add_hook(self)

    def shutdown(self):
        self.__class__.remove_hook(self)


class ExtensionHookPoint(type):
    """A metaclass used for base Extension Hooks.

    Base :py:class:`ExtensionHook` classes use :py:class:`ExtensionHookPoint`
    as a metaclass. This metaclass stores the list of registered hooks that
    an :py:class:`ExtensionHook` will automatically register with.
    """
    def __init__(cls, name, bases, attrs):
        super(ExtensionHookPoint, cls).__init__(name, bases, attrs)

        if not hasattr(cls, "hooks"):
            cls.hooks = []

    def add_hook(cls, hook):
        """Adds an ExtensionHook to the list of active hooks.

        This is called automatically by :py:class:`ExtensionHook`.
        """
        cls.hooks.append(hook)

    def remove_hook(cls, hook):
        """Removes an ExtensionHook from the list of active hooks.

        This is called automatically by :py:class:`ExtensionHook`.
        """
        cls.hooks.remove(hook)


class ExtensionManager(object):
    """A manager for all extensions.

    ExtensionManager manages the extensions available to a project. It can
    scan for new extensions, enable or disable them, determine dependencies,
    install into the database, and uninstall.

    An installed extension is one that has been installed by a Python package
    on the system.

    A registered extension is one that has been installed and information then
    placed in the database. This happens automatically after scanning for
    an installed extension. The registration data stores whether or not it's
    enabled, and stores various pieces of information on the extension.

    An enabled extension is one that is actively enabled and hooked into the
    project.

    Each project should have one ExtensionManager.
    """
    def __init__(self, key):
        self.key = key

        self.pkg_resources = None

        self._extension_classes = {}
        self._extension_instances = {}

        self._admin_ext_resolver = get_resolver(None)

        _extension_managers.append(self)

    def get_absolute_url(self):
        return self._admin_ext_resolver.reverse(
            "djblets.extensions.views.extension_list")

    def get_enabled_extension(self, extension_id):
        """Returns an enabled extension with the given ID."""
        if extension_id in self._extension_instances:
            return self._extension_instances[extension_id]

        return None

    def get_enabled_extensions(self):
        """Returns the list of all enabled extensions."""
        return self._extension_instances.values()

    def get_installed_extensions(self):
        """Returns the list of all installed extensions."""
        return self._extension_classes.values()

    def get_installed_extension(self, extension_id):
        """Returns the installed extension with the given ID."""
        if extension_id not in self._extension_classes:
            raise InvalidExtensionError(extension_id)

        return self._extension_classes[extension_id]

    def get_dependent_extensions(self, dependency_extension_id):
        """Returns a list of all extensions required by an extension."""
        if dependency_extension_id not in self._extension_instances:
            raise InvalidExtensionError(dependency_extension_id)

        dependency = self.get_installed_extension(dependency_extension_id)
        result = []

        for extension_id, extension in self._extension_classes.iteritems():
            if extension_id == dependency_extension_id:
                continue

            for ext_requirement in extension.info.requirements:
                if ext_requirement == dependency:
                    result.append(extension_id)

        return result

    def enable_extension(self, extension_id):
        """Enables an extension.

        Enabling an extension will install any data files the extension
        may need, any tables in the database, perform any necessary
        database migrations, and then will start up the extension.
        """
        if extension_id in self._extension_instances:
            # It's already enabled.
            return

        if extension_id not in self._extension_classes:
            raise InvalidExtensionError(extension_id)

        ext_class = self._extension_classes[extension_id]

        # Enable extension dependencies
        for requirement_id in ext_class.requirements:
            self.enable_extension(requirement_id)

        try:
            self._install_extension(ext_class)
        except InstallExtensionError, e:
            raise EnablingExtensionError(e.message)

        ext_class.registration.enabled = True
        ext_class.registration.save()
        return self._init_extension(ext_class)

    def disable_extension(self, extension_id):
        """Disables an extension.

        Disabling an extension will remove any data files the extension
        installed and then shut down the extension and all of its hooks.

        It will not delete any data from the database.
        """
        if extension_id not in self._extension_instances:
            # It's not enabled.
            return

        if extension_id not in self._extension_classes:
            raise InvalidExtensionError(extension_id)

        extension = self._extension_instances[extension_id]

        for dependent_id in self.get_dependent_extensions(extension_id):
            self.disable_extension(dependent_id)

        self._uninstall_extension(extension)
        self._uninit_extension(extension)
        extension.registration.enabled = False
        extension.registration.save()

    def load(self):
        """
        Loads all known extensions, initializing any that are recorded as
        being enabled.

        If this is called a second time, it will refresh the list of
        extensions, adding new ones and removing deleted ones.
        """
        # Preload all the RegisteredExtension objects
        registered_extensions = {}
        for registered_ext in RegisteredExtension.objects.all():
            registered_extensions[registered_ext.class_name] = registered_ext

        found_extensions = {}

        # Reload pkg_resources
        import pkg_resources
        if pkg_resources:
            del pkg_resources
            del sys.modules['pkg_resources']
            import pkg_resources

        for entrypoint in self._entrypoint_iterator():
            registered_ext = None

            try:
                ext_class = entrypoint.load()

                # Don't override the info if we've previously loaded this
                # class.
                if not getattr(ext_class, "info", None):
                    ext_class.info = ExtensionInfo(entrypoint, ext_class)
            except Exception, e:
                print "Error loading extension %s: %s" % (entrypoint.name, e)
                continue

            # A class's extension ID is its class name. We want to
            # make this easier for users to access by giving it an 'id'
            # variable, which will be accessible both on the class and on
            # instances.
            class_name = ext_class.id = "%s.%s" % (ext_class.__module__,
                                                   ext_class.__name__)
            self._extension_classes[class_name] = ext_class
            found_extensions[class_name] = ext_class

            # If the ext_class has a registration variable that's set, then
            # it's already been loaded. We don't want to bother creating a
            # new one.
            if not hasattr(ext_class, "registration"):
                if class_name in registered_extensions:
                    registered_ext = registered_extensions[class_name]
                else:
                    try:
                        registered_ext = RegisteredExtension.objects.get(
                            class_name=class_name)
                    except RegisteredExtension.DoesNotExist:
                        registered_ext = RegisteredExtension(
                            class_name=class_name,
                            name=entrypoint.dist.project_name
                        )
                        registered_ext.save()

                ext_class.registration = registered_ext

            if (ext_class.registration.enabled and
                not ext_class.id in self._extension_instances):
                self._init_extension(ext_class)

        # At this point, if we're reloading, it's possible that the user
        # has removed some extensions. Go through and remove any that we
        # can no longer find.
        #
        # While we're at it, since we're at a point where we've seen all
        # extensions, we can set the ExtensionInfo.requirements for
        # each extension
        for class_name, ext_class in self._extension_classes.iteritems():
            if class_name not in found_extensions:
                if class_name in self._extension_instances:
                    self.disable_extension(class_name)

                del self._extension_classes[class_name]
            else:
                ext_class.info.requirements = \
                    [self.get_installed_extension(requirement_id)
                     for requirement_id in ext_class.requirements]

    def _init_extension(self, ext_class):
        """Initializes an extension.

        This will register the extension, install any URLs that it may need,
        and make it available in Django's list of apps. It will then notify
        that the extension has been initialized.
        """
        assert ext_class.id not in self._extension_instances
        extension = ext_class()
        extension.extension_manager = self
        self._extension_instances[extension.id] = extension

        if extension.is_configurable:
            self._install_admin_urls(extension)

        extension.info.installed = extension.registration.installed
        extension.info.enabled = True
        self._add_to_installed_apps(extension)
        self._reset_templatetags_cache()
        extension_initialized.send(self, ext_class=extension)

        return extension

    def _uninit_extension(self, extension):
        """Uninitializes the extension.

        This will shut down the extension, remove any URLs, remove it from
        Django's list of apps, and send a signal saying the extension was
        shut down.
        """
        extension.shutdown()

        if hasattr(extension, "admin_urlpatterns"):
            for urlpattern in extension.admin_urlpatterns:
                self._admin_ext_resolver.url_patterns.remove(urlpattern)

        self._remove_from_installed_apps(extension)
        self._reset_templatetags_cache()
        extension.info.enabled = False
        extension_uninitialized.send(self, ext_class=extension)

        del self._extension_instances[extension.id]

    def _reset_templatetags_cache(self):
        """Clears the Django templatetags_modules cache."""
        # We'll import templatetags_modules here because
        # we want the most recent copy of templatetags_modules
        from django.template.base import get_templatetags_modules, \
                                         templatetags_modules
        # Wipe out the contents
        del(templatetags_modules[:])

        # And reload the cache
        get_templatetags_modules()

    def _install_extension(self, ext_class):
        """Installs extension data.

        Performs any installation necessary for an extension.
        This will install the contents of htdocs into the
        EXTENSIONS_STATIC_ROOT directory.
        """
        ext_path = ext_class.info.htdocs_path
        ext_path_exists = os.path.exists(ext_path)

        if ext_path_exists:
            # First, get rid of the old htdocs contents, so we can start
            # fresh.
            shutil.rmtree(ext_path, ignore_errors=True)

        if pkg_resources.resource_exists(ext_class.__module__, "htdocs"):
            # Now install any new htdocs contents.
            extracted_path = \
                pkg_resources.resource_filename(ext_class.__module__, "htdocs")

            shutil.copytree(extracted_path, ext_path, symlinks=True)

        # Mark the extension as installed
        ext_class.registration.installed = True
        ext_class.registration.save()

        # Now let's build any tables that this extension might need
        self._add_to_installed_apps(ext_class)

        # Call syncdb to create the new tables
        loading.cache.loaded = False
        call_command('syncdb', verbosity=0, interactive=False)

        # Run evolve to do any table modification
        try:
            evolution = Evolution()
            evolution.evolve(verbosity=0, interactive=False,
                             execute=True, hint=True,
                             compile_sql=False, purge=False,
                             database=False)
        except CommandError, e:
            # Something went wrong while running django-evolution, so
            # grab the output.  We can't raise right away because we
            # still need to put stdout back the way it was
            logging.error(e.message)
            raise InstallExtensionError(e.message)

        # Remove this again, since we only needed it for syncdb and
        # evolve.  _init_extension will add it again later in
        # the install.
        self._remove_from_installed_apps(ext_class)

        # Mark the extension as installed
        ext_class.registration.installed = True
        ext_class.registration.save()

    def _uninstall_extension(self, extension):
        """Uninstalls extension data.

        Performs any uninstallation necessary for an extension.
        This will uninstall the contents of
        EXTENSIONS_STATIC_ROOT/extension-name/.
        """
        ext_path = extension.info.htdocs_path
        ext_path_exists = os.path.exists(ext_path)

        if ext_path_exists:
            shutil.rmtree(ext_path, ignore_errors=True)

    def _install_admin_urls(self, extension):
        """Installs administration URLs.

        This provides URLs for configuring an extension, plus any additional
        admin urlpatterns that the extension provides.
        """
        urlconf = extension.admin_urlconf

        if hasattr(urlconf, "urlpatterns"):
            # Note that we're adding to the resolve list on the root of the
            # install, and prefixing it with the admin extensions path.
            # The reason we're not just making this a child of our extensions
            # urlconf is that everything in there gets passed an
            # extension_manager variable, and we don't want to force extensions
            # to handle this.
            prefix = self.get_absolute_url()

            extension.admin_urlpatterns = patterns('',
                (r'^%s%s/config/' % (prefix, extension.id),
                 include(urlconf.__name__)))

            self._admin_ext_resolver.url_patterns.extend(
                extension.admin_urlpatterns)

    def _add_to_installed_apps(self, extension):
        if extension.info.app_name not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(extension.info.app_name)

    def _remove_from_installed_apps(self, extension):
        if extension.info.app_name in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.remove(extension.info.app_name)

    def _entrypoint_iterator(self):
        return pkg_resources.iter_entry_points(self.key)


def get_extension_managers():
    return _extension_managers
