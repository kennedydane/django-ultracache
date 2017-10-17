"""Monkey patch template variable resolution so we can recognize which objects
are covered within a containing caching template tag. The patch is based on
Django 1.9 but is backwards compatible with 1.6."""

import inspect
import md5
import pickle
import types
from collections import OrderedDict

from django.core.cache import cache
from django.db.models import Model, Manager
from django.template.base import Variable, VariableDoesNotExist
from django.template.context import BaseContext
from django.contrib.contenttypes.models import ContentType
from django.conf import settings

from ultracache.utils import cache_meta, get_current_site_pk

try:
    from django.template.base import logger
except ImportError:
    logger = None


def _my_resolve_lookup(self, context):
        """
        Performs resolution of a real variable (i.e. not a literal) against the
        given context.

        As indicated by the method's name, this method is an implementation
        detail and shouldn"t be called by external code. Use Variable.resolve()
        instead.
        """
        current = context
        try:  # catch-all for silent variable failures
            for bit in self.lookups:
                try:  # dictionary lookup
                    current = current[bit]
                    # ValueError/IndexError are for numpy.array lookup on
                    # numpy < 1.9 and 1.9+ respectively
                except (TypeError, AttributeError, KeyError, ValueError, IndexError):
                    try:  # attribute lookup
                        # Don"t return class attributes if the class is the context:
                        if isinstance(current, BaseContext) and getattr(type(current), bit):
                            raise AttributeError
                        current = getattr(current, bit)
                    except (TypeError, AttributeError) as e:
                        # Reraise an AttributeError raised by a @property
                        if (isinstance(e, AttributeError) and
                                not isinstance(current, BaseContext) and bit in dir(current)):
                            raise
                        try:  # list-index lookup
                            current = current[int(bit)]
                        except (IndexError,  # list index out of range
                                ValueError,  # invalid literal for int()
                                KeyError,    # current is a dict without `int(bit)` key
                                TypeError):  # unsubscriptable object
                            raise VariableDoesNotExist("Failed lookup for key "
                                                       "[%s] in %r",
                                                       (bit, current))  # missing attribute
                if callable(current):
                    if getattr(current, "do_not_call_in_templates", False):
                        pass
                    elif getattr(current, "alters_data", False):
                        try:
                            current = context.template.engine.string_if_invalid
                        except AttributeError:
                            current = settings.TEMPLATE_STRING_IF_INVALID
                    else:
                        try:  # method call (assuming no args required)
                            current = current()
                        except TypeError:
                            try:
                                inspect.getcallargs(current)
                            except TypeError:  # arguments *were* required
                                try:
                                    current = context.template.engine.string_if_invalid  # invalid method call
                                except AttributeError:
                                    current = settings.TEMPLATE_STRING_IF_INVALID
                            else:
                                raise
                elif isinstance(current, Model):
                    if ("request" in context) and hasattr(context["request"], "_ultracache"):
                        # get_for_model itself is cached
                        ct = ContentType.objects.get_for_model(current.__class__)
                        print "ADD", ct.id, current.pk
                        context["request"]._ultracache.append((ct.id, current.pk))

        except Exception as e:
            template_name = getattr(context, "template_name", None) or "unknown"
            if logger is not None:
                logger.debug(
                    "Exception while resolving variable \"%s\" in template \"%s\".",
                    bit,
                    template_name,
                    exc_info=True,
                )

            if getattr(e, "silent_variable_failure", False):
                try:
                    current = context.template.engine.string_if_invalid
                except AttributeError:
                    current = settings.TEMPLATE_STRING_IF_INVALID
            else:
                raise

        return current

#Variable._resolve_lookup = _my_resolve_lookup


"""If Django Rest Framework is installed patch a few mixins. Serializers are
conceptually the same as templates but make it even easier to track objects."""
try:
    from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
    from rest_framework.response import Response
    from rest_framework.serializers import Serializer, ListSerializer
    HAS_DRF = True
except ImportError:
    HAS_DRF = False


def drf_cache(func):

    def wrapped(context, request, *args, **kwargs):
        viewsets = settings.ULTRACACHE.get("drf", {}).get("viewsets", {})
        dotted_name =  context.__module__ + "." + context.__class__.__name__
        do_cache = (dotted_name in viewsets) or (context.__class__ in viewsets) or ("*" in viewsets)

        if do_cache:
            li = [request.get_full_path()]
            viewset_settings = viewsets.get(dotted_name, {}) \
                or viewsets.get(context.__class__, {}) \
                or viewsets.get("*", {})
            evaluate = viewset_settings.get("evaluate", None)
            if evaluate is not None:
                if callable(evaluate):
                    li.append(evaluate(context, request))
                else:
                    li.append(eval(evaluate))

            if "django.contrib.sites" in settings.INSTALLED_APPS:
                li.append(get_current_site_pk(request))

            cache_key = md5.new(":".join([str(l) for l in li])).hexdigest()

            cached = cache.get(cache_key, None)
            if cached is not None:
                response = Response(pickle.loads(cached["content"]))

                # Headers has a non-obvious format
                for k, v in cached["headers"].items():
                    response[v[0]] = v[1]

                return response

        if not hasattr(request, "_ultracache"):
            setattr(request, "_ultracache", [])
            setattr(request, "_ultracache_cache_key_range", [])

        response = func(context, request, *args, **kwargs)

        if do_cache:
            cache_meta(request, cache_key)
            response = context.finalize_response(request, response, *args, **kwargs)
            response.render()
            timeout = viewset_settings.get("timeout", 300)
            headers = getattr(response, "_headers", {})
            cache.set(
                cache_key,
                {"content": pickle.dumps(response.data), "headers": headers},
                timeout
            )
            return response

        else:
            return response

    return wrapped


def _serializer(func):
    # Helper decorator for Serializer

    def wrapped(context, instance):
        request = context.context["request"]
        if hasattr(request, "_ultracache") and isinstance(instance, Model):
            ct = ContentType.objects.get_for_model(instance.__class__)
            request._ultracache.append((ct.id, instance.pk))
        return func(context, instance)

    return wrapped


def _listserializer(func):
    # Helper decorator for ListSerializer

    def wrapped(context, data):
        request = context.context["request"]
        if hasattr(request, "_ultracache"):
            iterable = data.all() if isinstance(data, Manager) else data
            for obj in iterable:
                if isinstance(obj, Model):
                    ct = ContentType.objects.get_for_model(obj.__class__)
                    request._ultracache.append((ct.id, obj.pk))
        return func(context, data)

    return wrapped


if HAS_DRF:
    ListModelMixin.list = drf_cache(ListModelMixin.list)
    RetrieveModelMixin.retrieve = drf_cache(RetrieveModelMixin.retrieve)
    Serializer.to_representation = _serializer(Serializer.to_representation)
    ListSerializer.to_representation = _listserializer(ListSerializer.to_representation)


from django.db.models import Model
from ultracache import _thread_locals

def mygetattr(self, name):
    print "getting %s" % name
    request = getattr(_thread_locals, "ultracache_request", None)
    if hasattr(request, "_ultracache"):
        instance = self
        # get_for_model itself is cached
        ct = ContentType.objects.get_for_model(instance.__class__)
        print "ADD", ct.id, instance.pk
        request._ultracache.append((ct.id, instance.pk))
    return super(Model, self).__getattribute__(name)

Model.__getattribute__ = mygetattr
