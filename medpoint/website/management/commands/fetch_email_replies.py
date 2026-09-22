from django.core.management.base import BaseCommand
from website.email_sync import sync_incoming_email_replies


class Command(BaseCommand):
    help = 'Connect to Gmail via IMAP and ingest incoming client replies for ContactMessage threads'

    def handle(self, *args, **options):
        self.stdout.write("Connecting to Gmail IMAP to check for client replies...")
        result = sync_incoming_email_replies()

        if result.get('success'):
            new_count = result.get('new_replies', 0)
            self.stdout.write(self.style.SUCCESS(f"Sync completed successfully. Ingested {new_count} new reply(s)."))
        else:
            error = result.get('error', 'Unknown error')
            self.stdout.write(self.style.ERROR(f"Sync failed: {error}"))
