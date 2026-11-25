from django.contrib import admin

from .models import ModerationAction, ShadowBan


@admin.register(ShadowBan)
class ShadowBanAdmin(admin.ModelAdmin):
    list_display = ('user_name', 'email', 'user', 'guest_key', 'created_by', 'created_at', 'lifted_at')
    list_filter = ('lifted_at',)
    raw_id_fields = ('user', 'created_by')


@admin.register(ModerationAction)
class ModerationActionAdmin(admin.ModelAdmin):
    list_display = ('kind', 'moderator', 'comment', 'shadow_ban', 'created_at')
    list_filter = ('kind',)
    raw_id_fields = ('moderator', 'comment', 'shadow_ban')
    readonly_fields = ('original_text',)
