"""The fixed demo research scope, independent of graph browsing and search."""
import re

SCOPE = {
    'id': 'grin-reduced-function-v1',
    'label': 'GRIN2A / GRIN2B',
    'description': 'GRIN2A/GRIN2B neurodevelopmental disorders: selected variants with evidence of reduced NMDA-receptor function, with provisional and opposing-function controls.',
}
# Subject-free follow-ups refer to the fixed demo, never a new disease cluster.
_FOLLOWUP_WORDS = set('''a an the this that these those our your my demo chosen selected cluster
what why which how main major strongest strong weak likely possible important is are was were does do can could should would will did has have
we i you it its they their them me us about for of to in on with from by and or
not no any all some more please tell show explain compare describe list find identify
help start get give see look into at between across as same different than there
here available recorded reported published known supporting supported support supports evidence
sources source papers paper study studies research findings finding observations observation
measurements measurement measured values value results result variants variant genes gene
connections connection connected related biology biological mechanism mechanisms function
functional loss reduced core provisional opposing controls control uncertain uncertainty
uncertainties conflicting conflict conflicts contradiction contradictions counter evidence
proof linked assertions limits limitations gaps gap missing next steps step resources resource assets asset
reuse reusable registry registries models model collaborators collaborator researchers researcher collaboration collaborations partners partner
recommendations recommendation recommend followup follow up priorities priority overview
summary atlas graph contains included inclusion exclusions excluded membership defines define classification
classifications methods method outcomes outcome assays assay protocols protocol issues issue
wt wild type comparisons comparison predictions prediction predictions versus vs counts many
who owns maintainers maintainer contacts contact opportunities opportunity matters matter
'''.split())
_INTENTS = set('evidence sources source papers paper measurements measurement variants variant genes gene connections connection mechanism mechanisms assets asset resources resource cluster overview summary atlas graph research conflicting conflicts uncertainty gaps next recommendations recommend registry collaborators partners observations observations limits limitations'.split())


_AMINO = dict(Ala='A', Arg='R', Asn='N', Asp='D', Cys='C', Gln='Q', Glu='E', Gly='G', His='H', Ile='I', Leu='L', Lys='K', Met='M', Phe='F', Pro='P', Ser='S', Thr='T', Trp='W', Tyr='Y', Val='V')


def mentions_scope(question, nodes=()):
    if re.search(r'\b(?:GRIN2[AB]|GluN2[AB]|NMDA(?:R)?|NMDARs)\b', question, re.I):
        return True
    for node in nodes:
        # The registered names/aliases include the supported variant shorthand.
        for term in [node.get('label', ''), *node.get('aliases', [])]:
            if not isinstance(term, str) or len(term) < 4:
                continue
            aliases = [term]
            if re.fullmatch(r'(?:p\.)?[A-Z][a-z]{2}\d+[A-Z][a-z]{2}', term):
                aliases += [term.removeprefix('p.'), re.sub(r'[A-Z][a-z]{2}', lambda m: _AMINO.get(m[0], m[0]), term.removeprefix('p.'))]
            if any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', question, re.I) for alias in aliases):
                return True
    return False


def question_in_scope(question, nodes=()):
    if mentions_scope(question, nodes):
        return True
    words = set(re.findall(r'[a-z0-9]+', question.casefold()))
    return bool(words & _INTENTS) and words <= _FOLLOWUP_WORDS


def scope_boundary(question, *, selected_label=None):
    selection = f'{selected_label} is outside the reviewed GRIN demo cluster. ' if selected_label else ''
    return {
        'answer': selection + 'Ask Atlas is focused on the GRIN2A/GRIN2B reduced-function research cluster. '
                  'I can explain its variant evidence, controls, research connections and assets. '
                  'Use the search at the top to explore all available graph entities; searching or selecting an entity does not change this demo focus. '
                  'An absent connection is a coverage gap, not evidence that no connection exists.',
        'mode': 'demo_scope_boundary', 'synthetic': False, 'claim_ids': [], 'node_ids': [],
        'suggestions': ['What evidence defines this cluster?', 'Which variants are provisional or opposing controls?'],
        'answer_scope': dict(SCOPE),
    }


def scoped_answer(answer):
    return {**answer, 'answer_scope': dict(SCOPE)}


class DemoScope:
    """Allowlist from the selected cluster; current evidence/reviews stay authoritative."""
    def __init__(self, bundle):
        self.nodes = bundle['nodes']
        self.node_ids = {n['id'] for n in self.nodes}
        self.claim_ids = {c['id'] for c in bundle['claims']}
        self.source_ids = {s['id'] for s in bundle['sources']}

    def project(self, bundle):
        claims = [c for c in bundle['claims'] if c['id'] in self.claim_ids
                  and c['subject'] in self.node_ids and c['object'] in self.node_ids]
        ids = {c['id'] for c in claims}
        return {**bundle,
                'nodes': [n for n in bundle['nodes'] if n['id'] in self.node_ids],
                'claims': claims,
                'evidence': [e for e in bundle['evidence'] if e['claim_id'] in ids and e['source_id'] in self.source_ids],
                'sources': [s for s in bundle['sources'] if s['id'] in self.source_ids],
                'coverage': []}


class DemoRetriever:
    """Only chat is scoped. The original catalog remains available to global search."""
    def __init__(self, catalog):
        self.catalog = catalog

    def search(self, query, top_k=8):
        return self.catalog.search(query, top_k=top_k, scope='grin')


def mentioned_external_genes(question, nodes, allowed_ids):
    # Match gene symbols, not substrings (ARX must not match ARXES1).
    tokens = set(re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', question.casefold())) - _FOLLOWUP_WORDS
    return [n for n in nodes if n.get('type') == 'Gene' and n['id'] not in allowed_ids
            and n.get('label', '').casefold() not in {'grin2a', 'grin2b'}
            and n.get('label', '').casefold() in tokens]
