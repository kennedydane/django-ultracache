# -*- coding: utf-8 -*-

from django import template
from django.conf.urls import include, url
from django.core.urlresolvers import reverse
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.test import TestCase
from django.test.client import Client, RequestFactory
from django.test.utils import override_settings
from django.conf import settings
from rest_framework.routers import DefaultRouter

from ultracache.tests.models import DummyModel, DummyForeignModel, \
    DummyOtherModel
from ultracache.tests import views, viewsets
from ultracache.tests.utils import dummy_proxy

router = DefaultRouter()
router.register(r"dummies", viewsets.DummyViewSet)

urlpatterns = [
    url(r'^api/', include(router.urls)),
    url(
        r'^render-view/$',
        views.RenderView.as_view(),
        name='render-view'
    ),
    url(
        r'^cached-view/$',
        views.CachedView.as_view(),
        name='cached-view'
    ),
    url(
        r'^cached-header-view/$',
        views.CachedHeaderView.as_view(),
        name='cached-header-view'
    ),
    url(
        r'^bustable-cached-view/$',
        views.BustableCachedView.as_view(),
        name='bustable-cached-view'
    ),
    url(
        r'^non-bustable-cached-view/$',
        views.NonBustableCachedView.as_view(),
        name='non-bustable-cached-view'
    ),
]

@override_settings(ROOT_URLCONF=__name__)
class TemplateTagsTestCase(TestCase):
    fixtures = ["sites.json"]

    @classmethod
    def setUpClass(cls):
        super(TemplateTagsTestCase, cls).setUpClass()
        cls.factory = RequestFactory()
        cls.request = cls.factory.get('/')
        cache.clear()
        dummy_proxy.clear()
        cls.first_site = Site.objects.all().first()
        cls.second_site = Site.objects.all().last()

    def test_sites(self):
        # Caching on same site
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache' %}1{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result1 = t.render(context)
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache' %}2{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result2 = t.render(context)
        self.assertEqual(result1, result2)

        # Caching on different sites
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache' %}1{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result1 = t.render(context)
        with override_settings(SITE_ID=self.second_site.id):
            t = template.Template("{%% load ultracache_tags %%}\
                {%% ultracache 1200 'test_ultracache' %%}%s{%% endultracache %%}" % self.second_site.id
            )
            context = template.Context({'request' : self.request})
            result2 = t.render(context)
            self.assertNotEqual(result1, result2)

    def test_variables(self):
        # Check that undefined variables do not break caching
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache_undefined' aaa %}1{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result1 = t.render(context)
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache_undefined' bbb %}2{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result2 = t.render(context)
        self.assertEqual(result1, result2)

        # Check that translation proxies are valid variables
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache_xlt' _('aaa') %}1{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result1 = t.render(context)
        t = template.Template("{% load ultracache_tags %}\
            {% ultracache 1200 'test_ultracache_xlt' _('aaa') %}2{% endultracache %}"
        )
        context = template.Context({'request' : self.request})
        result2 = t.render(context)
        self.assertEqual(result1, result2)

        # Check that large integer variables do not break caching
        t = template.Template("{%% load ultracache_tags %%}\
            {%% ultracache 1200 'test_ultracache_large' 565417614189797377 %%}%s{%% endultracache %%}" % self.second_site.id
        )
        context = template.Context({'request' : self.request})
        result1 = t.render(context)
        t = template.Template("{%% load ultracache_tags %%}\
            {%% ultracache 1200 'test_ultracache_large' 565417614189797377 %%}%s{%% endultracache %%}" % self.second_site.id
        )
        context = template.Context({'request' : self.request})
        result2 = t.render(context)
        self.assertEqual(result1, result2)


    def test_context_without_request(self):
        t = template.Template("{%% load ultracache_tags %%}\
            {%% ultracache 1200 'test_ultracache_undefined' aaa %%}%s{%% endultracache %%}" % self.first_site.id
        )
        context = template.Context()
        self.assertRaises(KeyError, t.render, context)

    def test_invalidation(self):
        """Directly render template
        """
        one = DummyModel.objects.create(title='One', code='one')
        two = DummyModel.objects.create(title='Two', code='two')
        three = DummyForeignModel.objects.create(title='Three', points_to=one, code='three')
        four = DummyOtherModel.objects.create(title='Four', code='four')
        # The counter is used to track the iteration that a cached block was
        # last rendered.
        t = template.Template("""{% load ultracache_tags ultracache_test_tags %}
            {% ultracache 1200 'test_ultracache_invalidate_outer' %}
                    counter outer = {{ counter }}
                {% ultracache 1200 'test_ultracache_invalidate_one' %}
                    title = {{ one.title }}
                    counter one = {{ counter }}
                {% endultracache %}
                {% ultracache 1200 'test_ultracache_invalidate_two' %}
                    title = {{ two.title }}
                    counter two = {{ counter }}
                {% endultracache %}
                {% ultracache 1200 'test_ultracache_invalidate_three' %}
                    title = {{ three.title }}
                    {{ three.points_to.title }}
                    counter three = {{ counter }}
                {% endultracache %}
                {% ultracache 1200 'test_ultracache_invalidate_render_view' %}
                    {% render_view 'render-view' %}
                {% endultracache %}
                {% ultracache 1200 'test_ultracache_invalidate_include %}
                    {% include "tests/include_me.html" %}
                {% endultracache %}
            {% endultracache %}"""
        )

        # Initial render
        request = self.factory.get('/aaa/')
        context = template.Context({
            'request' : request,
            'one': one,
            'two': two,
            'three': three,
            'counter': 1
        })
        result = t.render(context)
        dummy_proxy.cache('/aaa/', result)
        self.assertTrue('title = One' in result)
        self.assertTrue('title = Two' in result)
        self.assertTrue('counter outer = 1' in result)
        self.assertTrue('counter one = 1' in result)
        self.assertTrue('counter two = 1' in result)
        self.assertTrue('counter three = 1' in result)
        self.assertTrue('render_view = One' in result)
        self.assertTrue('include = One' in result)
        self.assertTrue(dummy_proxy.is_cached('/aaa/'))

        # Change object one
        one.title = 'Onxe'
        one.save()
        request = self.factory.get('/bbb/')
        context = template.Context({
            'request' : request,
            'one': one,
            'two': two,
            'three': three,
            'counter': 2
        })
        result = t.render(context)
        dummy_proxy.cache('/bbb/', result)
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Two' in result)
        self.assertTrue('counter outer = 2' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 1' in result)
        self.assertTrue('counter three = 2' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertFalse(dummy_proxy.is_cached('/aaa/'), msg=dummy_proxy["/aaa/"])

        # Change object two
        two.title = 'Twxo'
        two.save()
        request = self.factory.get('/ccc/')
        context = template.Context({
            'request' : request,
            'one': one,
            'two': two,
            'three': three,
            'counter': 3
        })
        result = t.render(context)
        dummy_proxy.cache('/ccc/', result)
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Twxo' in result)
        self.assertFalse('title = Two' in result)
        self.assertTrue('counter outer = 3' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 3' in result)
        self.assertTrue('counter three = 2' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertFalse(dummy_proxy.is_cached('/bbb/'))

        # Change object three
        three.title = 'Threxe'
        three.save()
        request = self.factory.get('/ddd/')
        context = template.Context({
            'request' : request,
            'one': one,
            'two': two,
            'three': three,
            'counter': 4
        })
        result = t.render(context)
        dummy_proxy.cache('/ddd/', result)
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Twxo' in result)
        self.assertFalse('title = Two' in result)
        self.assertTrue('title = Threxe' in result)
        self.assertFalse('title = Three' in result)
        self.assertTrue('counter outer = 4' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 3' in result)
        self.assertTrue('counter three = 4' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertFalse(dummy_proxy.is_cached('/ccc/'))

        # Add a DummyOtherModel object five
        five = DummyOtherModel.objects.create(title='Five', code='five')
        request = self.factory.get('/eee/')
        context = template.Context({
            'request' : request,
            'one': one,
            'two': two,
            'three': three,
            'counter': 5
        })
        result = t.render(context)
        dummy_proxy.cache('/eee/', result)
        # RenderView is only view aware of DummyOtherModel. That means
        # test_ultracache_invalidate_outer and
        # test_ultracache_invalidate_render_view are expired.
        self.assertTrue('render_view = Five' in result)
        self.assertTrue('counter outer = 5' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 3' in result)
        self.assertTrue('counter three = 4' in result)
        self.assertFalse(dummy_proxy.is_cached('/ddd/'))

        # Delete object two
        two.delete()
        request = self.factory.get('/fff/')
        context = template.Context({
            'request' : request,
            'one': one,
            'two': None,
            'three': three,
            'counter': 6
        })
        result = t.render(context)
        dummy_proxy.cache('/fff/', result)
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = Twxo' in result)
        self.assertFalse('title = Two' in result)
        self.assertTrue('counter outer = 6' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 6' in result)
        self.assertTrue('counter three = 4' in result)
        self.assertFalse(dummy_proxy.is_cached('/eee/'))

@override_settings(ROOT_URLCONF=__name__)
class DecoratorTestCase(TestCase):
    fixtures = ["sites.json"]

    @classmethod
    def setUpClass(cls):
        super(DecoratorTestCase, cls).setUpClass()
        cls.request = RequestFactory().get('/')
        cache.clear()
        dummy_proxy.clear()
        cls.first_site = Site.objects.all().first()
        cls.second_site = Site.objects.all().last()

    def test_decorator(self):
        """Render template through a view
        """
        one = DummyModel.objects.create(title='One', code='one')
        two = DummyModel.objects.create(title='Two', code='two')
        three = DummyForeignModel.objects.create(title='Three', points_to=one, code='three')
        four = DummyModel.objects.create(title='Four', code='four')
        url = reverse('cached-view')

        # Initial render
        views.COUNTER = 1
        response = self.client.get(url)
        result = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertTrue('title = One' in result)
        self.assertTrue('title = Two' in result)
        self.assertTrue('title = Three' in result)
        self.assertTrue('render_view = One' in result)
        self.assertTrue('include = One' in result, msg=result)
        self.assertTrue('counter one = 1' in result)
        self.assertTrue('counter two = 1' in result)
        self.assertTrue('counter three = 1' in result)
        self.assertTrue('counter four = 1' in result)
        self.assertTrue('title = Four' in result)

        # Change object one
        views.COUNTER = 2
        one.title = 'Onxe'
        one.save()
        response = self.client.get(url)
        result = response.content.decode()
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Two' in result)
        self.assertTrue('title = Three' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 1' in result)
        self.assertTrue('counter three = 2' in result)
        self.assertTrue('counter four = 2' in result)
        self.assertTrue('title = Four' in result)

        # Change object two
        views.COUNTER = 3
        two.title = 'Twxo'
        two.save()
        response = self.client.get(url)
        result = response.content.decode()
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Twxo' in result)
        self.assertFalse('title = Two' in result)
        self.assertTrue('title = Three' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 3' in result)
        self.assertTrue('counter three = 2' in result)
        self.assertTrue('counter four = 3' in result)
        self.assertTrue('title = Four' in result)

        # Change object three
        views.COUNTER = 4
        three.title = 'Threxe'
        three.save()
        response = self.client.get(url)
        result = response.content.decode()
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Twxo' in result)
        self.assertFalse('title = Two' in result)
        self.assertTrue('title = Threxe' in result)
        self.assertFalse('title = Three' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 3' in result)
        self.assertTrue('counter three = 4' in result)
        self.assertTrue('counter four = 4' in result)
        self.assertTrue('title = Four' in result)

        # Change object four
        views.COUNTER = 5
        four.title = 'Fouxr'
        four.save()
        response = self.client.get(url)
        result = response.content.decode()
        self.assertTrue('title = Onxe' in result)
        self.assertFalse('title = One' in result)
        self.assertTrue('title = Twxo' in result)
        self.assertFalse('title = Two' in result)
        self.assertTrue('title = Threxe' in result)
        self.assertFalse('title = Three' in result)
        self.assertTrue('counter one = 2' in result)
        self.assertTrue('counter two = 3' in result)
        self.assertTrue('counter three = 4' in result)
        self.assertTrue('counter four = 5' in result)
        self.assertTrue('render_view = Onxe' in result)
        self.assertTrue('include = Onxe' in result)
        self.assertTrue('title = Fouxr' in result)
        self.assertFalse('title = Four' in result)

    def test_decorator_header(self):
        """Test that decorator preserves headers
        """
        url = reverse('cached-header-view')

        # Initial render
        response = self.client.get(url)
        self.assertEqual(response._headers['content-type'], ('Content-Type', 'application/json'))
        self.assertEqual(response._headers['foo'], ('foo', 'bar'))

        # Second pass is cached
        response = self.client.get(url)
        self.assertEqual(response._headers['content-type'], ('Content-Type', 'application/json'))
        self.assertEqual(response._headers['foo'], ('foo', 'bar'))

    def test_decorator_cache_busting(self):
        """Test cache busting with and without random querystring param
        """
        url = reverse('bustable-cached-view')
        response = self.client.get(url + '?aaa=1')
        self.assertTrue('aaa=1' in response.content.decode())
        response = self.client.get(url + '?aaa=2')
        self.assertTrue('aaa=2' in response.content.decode())

        url = reverse('non-bustable-cached-view')
        response = self.client.get(url + '?aaa=1')
        self.assertTrue('aaa=1' in response.content.decode())
        response = self.client.get(url + '?aaa=2')
        self.assertFalse('aaa=2' in response.content.decode())
