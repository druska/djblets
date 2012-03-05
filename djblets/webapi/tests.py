#
# tests.py -- Unit tests for classes in djblets.webapi
#
# Copyright (c) 2011  Beanbag, Inc.
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

from django.test.client import RequestFactory

from djblets.util.testing import TestCase
from djblets.webapi.resources import WebAPIResource, unregister_resource


class WebAPIResourceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.test_resource = None

    def tearDown(self):
        if self.test_resource:
            unregister_resource(self.test_resource)

    def test_vendor_mimetypes(self):
        """Testing WebAPIResource with vendor-specific mimetypes"""
        class TestResource(WebAPIResource):
            mimetype_vendor = 'djblets'

        self.test_resource = TestResource()

        self.assertEqual(len(self.test_resource.allowed_list_mimetypes), 4)
        self.assertEqual(len(self.test_resource.allowed_item_mimetypes), 4)

        self.assertTrue('application/json' in
                        self.test_resource.allowed_list_mimetypes)
        self.assertTrue('application/xml' in
                        self.test_resource.allowed_list_mimetypes)
        self.assertTrue('application/vnd.djblets.testresources+json' in
                        self.test_resource.allowed_list_mimetypes)
        self.assertTrue('application/vnd.djblets.testresources+xml' in
                        self.test_resource.allowed_list_mimetypes)

        self.assertTrue('application/json' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/xml' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/vnd.djblets.testresource+json' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/vnd.djblets.testresource+xml' in
                        self.test_resource.allowed_item_mimetypes)

    def test_vendor_mimetypes_with_custom(self):
        """Testing WebAPIResource with vendor-specific and custom mimetypes"""
        class TestResource(WebAPIResource):
            mimetype_vendor = 'djblets'
            allowed_item_mimetypes = WebAPIResource.allowed_item_mimetypes + [
                'text/html',
            ]

        self.test_resource = TestResource()

        self.assertEqual(len(self.test_resource.allowed_list_mimetypes), 4)
        self.assertEqual(len(self.test_resource.allowed_item_mimetypes), 5)

        self.assertTrue('application/json' in
                        self.test_resource.allowed_list_mimetypes)
        self.assertTrue('application/xml' in
                        self.test_resource.allowed_list_mimetypes)
        self.assertTrue('application/vnd.djblets.testresources+json' in
                        self.test_resource.allowed_list_mimetypes)
        self.assertTrue('application/vnd.djblets.testresources+xml' in
                        self.test_resource.allowed_list_mimetypes)

        self.assertTrue('application/json' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/xml' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/vnd.djblets.testresource+json' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/vnd.djblets.testresource+xml' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('application/vnd.djblets.testresource+xml' in
                        self.test_resource.allowed_item_mimetypes)
        self.assertTrue('text/html' in
                        self.test_resource.allowed_item_mimetypes)

    def test_get_with_vendor_mimetype(self):
        """Testing WebAPIResource with GET and vendor-specific mimetypes"""
        class TestResource(WebAPIResource):
            allowed_methods = ('GET', 'POST', 'PUT', 'DELETE')
            mimetype_vendor = 'djblets'
            uri_object_key = 'id'

            def get(self, *args, **kwargs):
                return 200, {}

            create = get
            update = get
            delete = get

        self.test_resource = TestResource()
        self._test_mimetype_responses(
            self.test_resource,
            '/api/tests/',
            'application/vnd.djblets.testresources+json',
            'application/vnd.djblets.testresources+xml')
        self._test_mimetype_responses(
            self.test_resource,
            '/api/tests/',
            'application/vnd.djblets.testresource+json',
            'application/vnd.djblets.testresource+xml',
            method='post')

        self._test_mimetype_responses(
            self.test_resource,
            '/api/tests/1/',
            'application/vnd.djblets.testresource+json',
            'application/vnd.djblets.testresource+xml',
            view_kwargs={'id': 1},
            method='put')
        self._test_mimetype_responses(
            self.test_resource,
            '/api/tests/1/',
            'application/vnd.djblets.testresource+json',
            'application/vnd.djblets.testresource+xml',
            view_kwargs={'id': 1},
            method='delete')


    def _test_mimetype_responses(self, resource, url, json_mimetype,
                                 xml_mimetype, **kwargs):
        self._test_mimetype_response(resource, url, '*/*', json_mimetype,
                                     **kwargs)
        self._test_mimetype_response(resource, url, 'application/json',
                                     json_mimetype, **kwargs)
        self._test_mimetype_response(resource, url, json_mimetype,
                                     json_mimetype, **kwargs)
        self._test_mimetype_response(resource, url, 'application/xml',
                                     xml_mimetype, **kwargs)
        self._test_mimetype_response(resource, url, xml_mimetype, xml_mimetype,
                                     **kwargs)

    def _test_mimetype_response(self, resource, url, accept_mimetype,
                                response_mimetype, method='get',
                                view_kwargs={}):
        func = getattr(self.factory, method)

        if accept_mimetype:
            request = func(url, HTTP_ACCEPT=accept_mimetype)
        else:
            request = func(url)

        response = resource(request, **view_kwargs)
        print response
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], response_mimetype)
