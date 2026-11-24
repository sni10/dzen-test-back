from django.contrib import admin

from .models import Attachment, Bookmark, Comment, CommentVote


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ('kind', 'file', 'original_name', 'size', 'width', 'height', 'status', 'created_at')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_name', 'email', 'parent', 'depth', 'score', 'is_ufo', 'is_shadowed', 'created_at')
    list_filter = ('is_ufo', 'is_shadowed')
    search_fields = ('user_name', 'email', 'text')
    raw_id_fields = ('parent', 'root', 'user')
    readonly_fields = ('replies_count', 'score', 'ip', 'user_agent', 'guest_key', 'created_at')
    inlines = [AttachmentInline]


@admin.register(CommentVote)
class CommentVoteAdmin(admin.ModelAdmin):
    list_display = ('comment', 'user', 'value', 'updated_at')
    raw_id_fields = ('comment', 'user')


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ('user', 'comment', 'created_at')
    raw_id_fields = ('comment', 'user')
