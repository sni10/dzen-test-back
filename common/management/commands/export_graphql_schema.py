from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from config.graphql import schema

SCHEMA_FILE = Path(settings.BASE_DIR) / 'schema.graphql'


class Command(BaseCommand):
    help = 'Write the GraphQL schema to schema.graphql (committed; a test checks it is up to date).'

    def handle(self, *args, **options):
        SCHEMA_FILE.write_text(schema.as_str() + '\n', encoding='utf-8', newline='\n')
        self.stdout.write(self.style.SUCCESS(f'Written {SCHEMA_FILE.name}'))
