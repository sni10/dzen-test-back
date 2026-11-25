from django.core.management.base import BaseCommand

from comments.container import search_index
from comments.models import Comment

BATCH = 5000


class Command(BaseCommand):
    help = 'Rebuild the search index from the database (after a mapping change or on a new server).'

    def handle(self, *args, **options):
        index = search_index()
        index.recreate()
        # No refreshes while loading a million documents: one at the end
        index.client.indices.put_settings(index=index.index, settings={'refresh_interval': '-1'})
        total = 0
        batch = []
        for comment in Comment.objects.order_by('pk').iterator(chunk_size=BATCH):
            batch.append(comment)
            if len(batch) == BATCH:
                index.save(batch, wait=False)
                total += len(batch)
                batch = []
                if total % 100_000 == 0:
                    self.stdout.write(f'  {total:,}')
        if batch:
            index.save(batch, wait=False)
            total += len(batch)
        index.client.indices.put_settings(index=index.index, settings={'refresh_interval': None})  # default
        index.client.indices.refresh(index=index.index)
        self.stdout.write(self.style.SUCCESS(f'Indexed {total} comments into "{index.index}"'))
