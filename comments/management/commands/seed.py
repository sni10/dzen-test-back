"""Fill the database with generated comments for the load test (1 000 000 by default).

Plain multi-row INSERTs with explicit ids, not the ORM: a million model instances would take far longer and
`auto_now_add` would stamp them all with the same moment. The tree is planned first (who replies to whom),
so `root`, `depth` and `replies_count` are written right away and need no second pass.
Seeded rows carry the user agent `seed` (load-test posts `seed (locust)`): `--clear` removes them, nothing else.
"""
import random
from array import array
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from comments import stats
from comments.models import Comment

SEED_AGENT = 'seed'
BATCH = 5000
MAX_DEPTH = 6  # replies to a deep comment go to its ancestor: realistic threads, not endless chains
COLUMNS = ('id', 'parent_id', 'root_id', 'depth', 'user_name', 'email', 'home_page', 'text', 'is_ufo',
           'is_shadowed', 'by_moderator', 'replies_count', 'score', 'ip', 'user_agent', 'created_at')

NAMES = ['Anonym', 'Rum8', 'Ivan', 'Olena', 'Dmytro', 'Kate', 'Max', 'Sofia', 'Andrii', 'Nina', 'Alex', 'Taras']
WORDS = ('comment reply thread question answer idea review release bug feature search moderation queue cache '
         'комментарий ответ ветка вопрос идея обзор релиз ошибка поиск модерация очередь кэш сервер база').split()


class Command(BaseCommand):
    help = 'Generate comments for the load test (top-level threads with replies, spread over the past year).'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=1_000_000)
        parser.add_argument('--top-share', type=float, default=0.2, help='share of top-level comments')
        parser.add_argument('--clear', action='store_true', help='delete the seeded comments and exit')

    def handle(self, *args, count, top_share, clear, **options):
        if clear:
            with connection.cursor() as cursor:
                # The load test posts as `seed (locust)`; the deepest first: the foreign keys have no ON DELETE
                cursor.execute(f'DELETE FROM {Comment._meta.db_table} WHERE user_agent LIKE %s ORDER BY depth DESC',
                               [f'{SEED_AGENT}%'])
                self.stdout.write(self.style.SUCCESS(f'Deleted {cursor.rowcount} seeded comments'))
            stats.invalidate()
            return

        rng = random.Random(42)
        first_id = (Comment.objects.order_by('-pk').values_list('pk', flat=True).first() or 0) + 1

        # The plan: parent[i] is the index of the parent (-1 for top level); replies go to recent comments,
        # as in a live discussion
        parent = array('l', [-1]) * count
        root = array('l', range(count))
        depth = array('H', [0]) * count
        replies = array('L', [0]) * count
        for i in range(1, count):
            if rng.random() >= top_share:
                p = rng.randrange(max(0, i - 2000), i)
                while depth[p] >= MAX_DEPTH:
                    p = parent[p]
                parent[i], root[i], depth[i] = p, root[p], depth[p] + 1
                replies[p] += 1

        # Oldest first, ~ evenly over the past year: the newest id is the newest comment
        end = timezone.now().replace(tzinfo=None)  # naive UTC, as Django stores it (USE_TZ)
        step = timedelta(days=365) / count
        table = Comment._meta.db_table
        sql = f'INSERT INTO {table} ({", ".join(COLUMNS)}) VALUES ({", ".join(["%s"] * len(COLUMNS))})'

        with connection.cursor() as cursor:
            for start in range(0, count, BATCH):
                rows = []
                for i in range(start, min(start + BATCH, count)):
                    name = rng.choice(NAMES)
                    rows.append((
                        first_id + i,
                        first_id + parent[i] if parent[i] >= 0 else None,
                        first_id + root[i] if parent[i] >= 0 else None,
                        depth[i],
                        name,
                        f'{name.lower()}{i % 1000}@example.com',
                        '',
                        ' '.join(rng.choices(WORDS, k=rng.randint(4, 30))),
                        False, False, False,
                        replies[i],
                        rng.randint(-3, 12) if rng.random() < 0.1 else 0,
                        '127.0.0.1',
                        SEED_AGENT,
                        end - step * (count - i),
                    ))
                cursor.executemany(sql, rows)  # mysqlclient sends one multi-row INSERT per batch
                if (start // BATCH) % 20 == 0:
                    self.stdout.write(f'  {start + len(rows):,} / {count:,}')

        stats.invalidate()
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {count:,} comments (ids {first_id}..{first_id + count - 1}). '
            'For search over them: manage.py reindex'))
