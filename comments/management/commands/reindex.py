from django.core.management.base import BaseCommand

from comments.container import search_index
from comments.models import Comment

BATCH = 1000


class Command(BaseCommand):
    help = 'Rebuild the search index from the database (after a mapping change or on a new server).'

    def handle(self, *args, **options):
        index = search_index()
        index.recreate()
        total = 0
        batch = []
        for comment in Comment.objects.order_by('pk').iterator(chunk_size=BATCH):
            batch.append(comment)
            if len(batch) == BATCH:
                index.save(batch)
                total += len(batch)
                batch = []
        if batch:
            index.save(batch)
            total += len(batch)
        self.stdout.write(self.style.SUCCESS(f'Indexed {total} comments into "{index.index}"'))
