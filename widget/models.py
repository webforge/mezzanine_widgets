from datetime import datetime

from django.contrib.sites.models import Site
from django.utils.translation import ugettext as _, ugettext
from django.db import models

from mezzanine.conf import settings
from mezzanine.core.managers import PublishedManager, SearchableManager, CurrentSiteManager
from mezzanine.core.models import Orderable, \
    CONTENT_STATUS_CHOICES, CONTENT_STATUS_DRAFT, Ownable, SiteRelated

from .option_fields import TEXT
from mezzanine.pages.models import Page

from widget.fields import PageWidgetClass

from django.db.models import Q
from django.utils.timezone import now


class WidgetOption(object):
    """
    Definition of a widget option
    """

    def __init__(self, **kwargs):
        self.name = kwargs.get("name", None)
        self.field_type = kwargs.get("field_type", TEXT)
        self.default = kwargs.get("default", None)
        self.field_args = kwargs.get("field_args", {})
        self.help_text = kwargs.get("help_text", \
                        "I am supposed to do something")
        self.required = kwargs.get("required", False)


class WidgetClassBase(object):
    """
    Base class for all widget plugin classes
    """
    editableFields = ""
    template = None
    raw = False 

    def _render(self, context, slot, queryset=None, options=None):
        """
        calls implemented render function and adds additional elements to the
        generated context
        """
        try:
            kwargs = {"context": context, "slot": slot, "queryset": queryset, "options": options}
            context = self.render(**kwargs)
        except Exception, e:
            raise e
        if hasattr(self, 'model'):
            context.update({'model': self.model})
        return context

    def render(self, **kwargs):
        raise NotImplementedError("Render function needs to be implemented")

    def cleanup(self, **kwargs):
        return True

class WidgetModel(SiteRelated):
    widget = models.ForeignKey('widget.Widget')

    def __unicode__(self):
        return u'Model for widget <%s>' % self.widget.widget_class


class WidgetManager(CurrentSiteManager, PublishedManager, SearchableManager):
    """
    Manually combines ``CurrentSiteManager``, ``SearchableManager`` and provides a modified
    published filter which takes into cconsideration the users change permission
    for the ``Widget`` model.

    """
    def published(self, for_user=None):
        """
        For non-staff/permissionless users, return items with a published status and
        whose publish and expiry dates fall before and after the
        current date when specified.
        :param for_user:
        """
        from mezzanine.core.models import CONTENT_STATUS_PUBLISHED
        from widget.utilities import widget_extra_permission

        #This allows a callback for extra user validation, eg. check if a user passes a test (has a subscription)
        if for_user is not None and bool(for_user.is_staff
            or bool(for_user.has_perm("widget.change_widget") and widget_extra_permission(for_user))):
            return self.all()
        return self.filter(
            Q(publish_date__lte=now()) | Q(publish_date__isnull=True),
            Q(expiry_date__gte=now()) | Q(expiry_date__isnull=True),
            Q(status=CONTENT_STATUS_PUBLISHED))

    def widget_models(self):
        return WidgetModel.objects.filter(widget=self)

    def published_for_page_or_pageless(self, page, slot=None, for_user=None):
        """
        For non-staff/permissionless users, return items with that are published and
        belong to a certain page or page less
        """

        if slot:
            return self.published(for_user).filter(widgetslot=slot).filter(
                Q(page=page, page_less=False) | Q(page_less=True))
        else:
            return self.published(for_user).filter(
                Q(page=page, page_less=False) | Q(page_less=True))


class Widget(Orderable, Ownable, SiteRelated):
    display_title = models.CharField(
        default=None, verbose_name="Title", max_length=255, null=False)
    widget_class = PageWidgetClass(default="", verbose_name="Widget Type")
    active = models.BooleanField(default=True)
    widget_file_title = models.CharField(max_length=255, editable=False)
    author = models.CharField(max_length=255, editable=False)
    acts_on = models.CharField(max_length=255, editable=False)
    widgetslot = models.CharField(max_length=255, default="none")
    page_less = models.BooleanField(default=False)
    page = models.ForeignKey(Page, null=True, blank=True)
    status = models.IntegerField(_("Publish Status"),
        choices=CONTENT_STATUS_CHOICES, default=CONTENT_STATUS_DRAFT)
    publish_date = models.DateTimeField(_("Published from"),
        help_text=_("With published checked, won't be shown until this time"),
        blank=True, null=True)
    expiry_date = models.DateTimeField(_("Expires on"),
        help_text=_("With published checked, won't be shown after this time"),
        blank=True, null=True)


    objects = WidgetManager()
    search_fields = {"keywords": 10, "display_title": 5}

    def save(self, update_site=True, *args, **kwargs):
        """
        Set default for ``publsh_date`` and ``description`` if none
        given. Unless the ``update_site`` argument is ``False``, set
        the site to the current site.
        """

        from widget.widget_pool import get_widget
        widg = get_widget(self.widget_class)
        if hasattr(widg, 'Meta'):
            self.author = widg.Meta.author
            if hasattr(widg.Meta, 'page_less'): 
                self.page_less = widg.Meta.page_less
                self.page = None
        else:
            self.author = ''
            self.acts_on = ''
        if self.publish_date is None:
            self.publish_date = datetime.now()
        if update_site:
            self.site = Site.objects.get_current()
        """Some widget classes can appear on all pages.
        E.g those placed in the base template"""
        if self.page == None:
            self.page_less = True

        """Generate Widget Title"""
        if self.display_title is None:
            self.display_title = "%s_%s" %(self.widget_class, Widget.objects.count()+1)

        super(Widget, self).save(*args, **kwargs)

    def __unicode__(self):
        return unicode(self.display_title)

    def get_class(self):
        return self.widget_class

    @property
    def hasOptions(self):
        try:
            from widget.widget_pool import get_widget
            widg = get_widget(self.widget_class)
            return hasattr(widg, "options")
        except Exception, e:
            return False

    def admin_link(self):
        if not self.page_less:
            return "<a href='%s'>%s</a>" % (self.page.get_absolute_url(),
                                        ugettext("View on site"))
        else:
            return ""

    admin_link.allow_tags = True
    admin_link.short_description = ""


    class Meta:
        verbose_name = _("Widget")
        verbose_name_plural = _("Widgets")
        ordering = ("display_title",) 


class WidgetOptionGroup(SiteRelated):
    """
    A group of option entries for a widget
    """

    widget = models.OneToOneField("Widget", related_name="option_group")
    entry_time = models.DateTimeField(_("Date/time"))

    def __unicode__(self):
        return '' or "%s Option Group" % self.widget

    class Meta:
        verbose_name = _("Widget Option Group")
        verbose_name_plural = _("Widget Option Group's")


class WidgetOptionEntry(SiteRelated):

    """
    A single option value for a form entry submitted via a user-built form.
    """

    widget = models.ForeignKey("Widget", \
                    related_name="options")
    name = models.CharField(max_length=255)
    value = models.CharField(max_length=settings.FORMS_FIELD_MAX_LENGTH)

    def __unicode__(self):
        return '' or '%s [%s]' % (self.name, self.value)

    class Meta:
        verbose_name = _("Widget Option entry")
        verbose_name_plural = _("Widget Option entries")
