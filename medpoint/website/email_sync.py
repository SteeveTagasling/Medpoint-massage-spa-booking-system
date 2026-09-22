import imaplib
import email
from email.header import decode_header
import re
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from .models import ContactMessage, MessageReply

logger = logging.getLogger(__name__)


def decode_mime_header(header_value):
    """Safely decode MIME headers like Subject or From."""
    if not header_value:
        return ""
    decoded_fragments = decode_header(header_value)
    result = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            try:
                result.append(fragment.decode(encoding or 'utf-8', errors='replace'))
            except Exception:
                result.append(fragment.decode('utf-8', errors='replace'))
        else:
            result.append(str(fragment))
    return "".join(result).strip()


def extract_email_address(from_header):
    """Extract clean email address and name from a From header."""
    if not from_header:
        return "", ""
    match = re.search(r'^(.*?)\s*<([^>]+)>$', from_header.strip())
    if match:
        name = match.group(1).strip(' "\'')
        email_addr = match.group(2).strip().lower()
        return name, email_addr
    if '@' in from_header:
        return from_header.split('@')[0].strip(), from_header.strip().lower()
    return from_header.strip(), ""


def clean_email_body(text):
    """Strip quoted reply text (e.g. 'On ... wrote:', '--- Original Message ---', quotes)."""
    if not text:
        return ""

    lines = []
    stop_reply_patterns = [
        r'^\s*On\s+.+wrote:\s*$',
        r'^\s*-{2,}\s*Original Message\s*-{2,}',
        r'^\s*_{2,}\s*$',
        r'^\s*From:\s*.+',
        r'^\s*Sent from my\s+.+',
        r'^\s*Get Outlook for\s+.+',
    ]

    for line in text.splitlines():
        # Check if line marks the beginning of quoted previous email
        if any(re.match(pattern, line, re.IGNORECASE) for pattern in stop_reply_patterns):
            break
        # Skip quoted lines starting with '>'
        if line.strip().startswith('>'):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else text.strip()


def extract_body_from_email(msg_obj):
    """Extract plain text or HTML body from a python email.message object."""
    body_text = ""
    if msg_obj.is_multipart():
        for part in msg_obj.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition', ''))

            if 'attachment' in content_disposition:
                continue

            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                try:
                    body_text = payload.decode(charset, errors='replace')
                    break
                except Exception:
                    pass
            elif content_type == 'text/html' and not body_text:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                try:
                    from django.utils.html import strip_tags
                    body_text = strip_tags(payload.decode(charset, errors='replace'))
                except Exception:
                    pass
    else:
        payload = msg_obj.get_payload(decode=True)
        charset = msg_obj.get_content_charset() or 'utf-8'
        try:
            body_text = payload.decode(charset, errors='replace')
        except Exception:
            body_text = str(payload)

    return clean_email_body(body_text)


def find_matching_contact_message(subject, from_email, references_header=""):
    """
    Find corresponding ContactMessage:
    1. By explicit ticket ID in subject [Ticket #123] or [Ref: #123]
    2. By In-Reply-To / References header containing <ticket-123-...>
    3. Fallback: sender email matching most recent active ContactMessage
    """
    # 1. Look for [Ticket #123] in subject
    ticket_match = re.search(r'\[(?:Ticket|Ref|ID)\s*#?(\d+)\]', subject, re.IGNORECASE)
    if ticket_match:
        msg_id = int(ticket_match.group(1))
        contact = ContactMessage.objects.filter(pk=msg_id).first()
        if contact:
            return contact

    # 2. Look in References header: e.g. <ticket-123-reply@...>
    if references_header:
        ref_match = re.search(r'<ticket-(\d+)-', references_header, re.IGNORECASE)
        if ref_match:
            msg_id = int(ref_match.group(1))
            contact = ContactMessage.objects.filter(pk=msg_id).first()
            if contact:
                return contact

    # 3. Fallback: match by sender email address
    if from_email:
        contact = ContactMessage.objects.filter(email__iexact=from_email).order_by('-created_at').first()
        if contact:
            return contact

    return None


def sync_incoming_email_replies():
    """
    Connect to Gmail via IMAP, scan for new customer replies,
    and associate them with the respective ContactMessage thread.
    Returns dict: {'success': bool, 'new_replies': int, 'error': str (optional)}
    """
    email_user = getattr(settings, 'EMAIL_HOST_USER', None)
    email_password = getattr(settings, 'EMAIL_HOST_PASSWORD', None)

    if not email_user or not email_password:
        return {'success': False, 'error': 'Gmail credentials are not configured in settings.'}

    imap_host = 'imap.gmail.com'
    new_replies_count = 0

    try:
        mail = imaplib.IMAP4_SSL(imap_host, port=993)
        mail.login(email_user, email_password)
        mail.select('INBOX')

        # Scan messages from the past 14 days
        since_date = (timezone.now() - timedelta(days=14)).strftime("%d-%b-%Y")
        status, search_data = mail.search(None, f'(SINCE "{since_date}")')

        if status != 'OK' or not search_data or not search_data[0]:
            mail.logout()
            return {'success': True, 'new_replies': 0}

        msg_ids = search_data[0].split()
        # Scan recent messages (last 50 max to ensure fast response)
        msg_ids = msg_ids[-50:]

        for m_id in reversed(msg_ids):
            try:
                res, data = mail.fetch(m_id, '(RFC822)')
                if res != 'OK' or not data or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Message-ID header (unique message identifier)
                message_id = msg.get('Message-ID', '').strip()
                if not message_id:
                    message_id = f"imap-{m_id.decode()}"

                # Skip if already ingested
                if MessageReply.objects.filter(email_message_id=message_id).exists():
                    continue

                from_raw = decode_mime_header(msg.get('From', ''))
                sender_name, from_email = extract_email_address(from_raw)

                # Skip emails sent by ourselves
                if email_user.lower() in from_email.lower():
                    continue

                subject = decode_mime_header(msg.get('Subject', ''))
                references = msg.get('References', '') or msg.get('In-Reply-To', '')

                contact_msg = find_matching_contact_message(subject, from_email, references)
                if not contact_msg:
                    # Not a reply to a known ticket
                    continue

                # Extract cleaned reply body
                clean_body = extract_body_from_email(msg)
                if not clean_body:
                    continue

                # Create the client reply
                MessageReply.objects.create(
                    message=contact_msg,
                    sender_type=MessageReply.SENDER_CLIENT,
                    sender_name=sender_name or contact_msg.name,
                    sender_email=from_email or contact_msg.email,
                    body=clean_body,
                    email_message_id=message_id,
                )

                # Mark the parent contact message as unread so admin notices it
                contact_msg.is_read = False
                contact_msg.save(update_fields=['is_read'])

                new_replies_count += 1
                logger.info(f"Ingested client email reply for ticket #{contact_msg.pk} from {from_email}")

            except Exception as item_err:
                logger.warning(f"Error parsing email item: {item_err}")
                continue

        try:
            mail.close()
            mail.logout()
        except Exception:
            pass

        return {'success': True, 'new_replies': new_replies_count}

    except Exception as e:
        logger.error(f"IMAP sync failed: {e}")
        return {'success': False, 'error': str(e), 'new_replies': new_replies_count}
