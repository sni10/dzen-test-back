from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'is_shadowbanned', 'is_staff', 'date_joined')
    list_filter = ('role', 'is_shadowbanned', 'is_staff', 'is_superuser')
    fieldsets = BaseUserAdmin.fieldsets + (('Comments', {'fields': ('home_page', 'role', 'is_shadowbanned')}),)
