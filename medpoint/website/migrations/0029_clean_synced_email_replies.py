import html
import re

from django.db import migrations, models


def clean_body(text):
    if not text:
        return ''
    normalized = html.unescape(str(text)).replace('\r\n', '\n').replace('\r', '\n').replace('\xa0', ' ')
    patterns = [
        r'(?ims)^\s*On\s+.{1,1200}?\bwrote:\s*$',
        r'(?im)^\s*-{2,}\s*(?:Original Message|Forwarded message)\s*-{2,}\s*$',
        r'(?im)^\s*Begin forwarded message:\s*$',
        r'(?im)^\s*_{5,}\s*$',
    ]
    positions = []
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            positions.append(match.start())
    if positions:
        normalized = normalized[:min(positions)]
    kept = []
    for line in normalized.splitlines():
        if re.match(r'^\s*(?:From:|Sent:|Sent from my|Get Outlook for)\s*.+', line, re.IGNORECASE):
            break
        if not line.strip().startswith('>'):
            kept.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(kept)).strip()


def clean_and_deduplicate(apps, schema_editor):
    MessageReply = apps.get_model('website', 'MessageReply')
    seen_ids = set()
    for reply in MessageReply.objects.exclude(email_message_id__isnull=True).order_by('created_at', 'pk'):
        message_id = (reply.email_message_id or '').strip().casefold()
        if not message_id:
            reply.email_message_id = None
            reply.save(update_fields=['email_message_id'])
            continue
        if message_id in seen_ids:
            reply.delete()
            continue
        seen_ids.add(message_id)
        cleaned = clean_body(reply.body)
        changes = []
        if cleaned and cleaned != reply.body:
            reply.body = cleaned
            changes.append('body')
        if message_id != reply.email_message_id:
            reply.email_message_id = message_id
            changes.append('email_message_id')
        if changes:
            reply.save(update_fields=changes)


class Migration(migrations.Migration):
    dependencies = [
        ('website', '0028_ensure_legacy_service_categories'),
    ]

    operations = [
        migrations.RunPython(clean_and_deduplicate, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='messagereply',
            name='email_message_id',
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
    ]
