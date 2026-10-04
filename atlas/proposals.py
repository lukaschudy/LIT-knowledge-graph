"""Validated, private suggestions. Accepting a proposal never changes the graph."""
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit

SCHEMA = """CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
    created_at INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
)"""
INDEX = "CREATE INDEX IF NOT EXISTS proposals_created ON proposals(created_at)"
MAX_BYTES = 12000


class ProposalError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_proposal(data):
    if not isinstance(data, dict):
        raise ProposalError('Submit a JSON object.')
    fields = {'request_id': (36, 36), 'query': (0, 1000), 'name': (2, 160),
              'kind': (1, 30), 'description': (10, 4000), 'source_url': (0, 1500),
              'entry': (1, 20)}
    clean = {}
    for key, (minimum, maximum) in fields.items():
        value = data.get(key, '')
        if not isinstance(value, str):
            raise ProposalError(f'{key} must be text.')
        value = value.strip()
        if not minimum <= len(value) <= maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ProposalError(f'Check {key}: use {minimum}–{maximum} characters.')
        clean[key] = value
    try:
        if str(uuid.UUID(clean['request_id'])) != clean['request_id']:
            raise ValueError()
    except ValueError:
        raise ProposalError('Invalid submission reference.') from None
    if clean['kind'] not in {'gene', 'variant', 'disease', 'paper', 'relationship', 'other'}:
        raise ProposalError('Choose an item type.')
    if clean['entry'] not in {'chat', 'search', 'direct'}:
        raise ProposalError('Invalid form origin.')
    if clean['source_url']:
        try:
            url = urlsplit(clean['source_url'])
            if url.scheme not in {'https', 'http'} or not url.hostname or url.username or url.password:
                raise ValueError()
            url.port
        except ValueError:
            raise ProposalError('Use a complete http or https source URL without credentials.') from None
    return clean


def submit_proposal(data, execute, now=None):
    """execute(sql, *parameters) returns dictionaries, on SQLite or Durable SQL.

    Caller serializes this synchronous operation; there are no awaits between
    reads and the insert. The Worker Durable Object supplies that guarantee.
    """
    clean = validate_proposal(data)
    request_id = clean.pop('request_id')
    payload = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    existing = execute('SELECT id, fingerprint, status, created_at FROM proposals WHERE request_id = ?', request_id)
    if existing:
        row = existing[0]
        if row['fingerprint'] != fingerprint:
            raise ProposalError('This submission reference was already used. Start a new proposal.', 409)
        return 200, {k: row[k] for k in ('id', 'status', 'created_at')}
    now = int(time.time()) if now is None else now
    recent = execute('SELECT COUNT(*) AS count FROM proposals WHERE created_at > ?', now - 3600)[0]['count']
    if recent >= 120:
        raise ProposalError('The review inbox is receiving many submissions. Please try again later.', 429)
    receipt = {'id': str(uuid.uuid4()), 'status': 'pending_review', 'created_at': now}
    execute('INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?)', receipt['id'], request_id,
            fingerprint, now, receipt['status'], payload)
    return 201, receipt


def proposal_status(identifier, execute):
    try:
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError()
    except ValueError:
        raise ProposalError('Unknown proposal receipt.', 404) from None
    rows = execute('SELECT id, status, created_at FROM proposals WHERE id = ?', identifier)
    if not rows:
        raise ProposalError('Unknown proposal receipt.', 404)
    return rows[0]
