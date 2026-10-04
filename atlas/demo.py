"""A larger, reproducible synthetic atlas for the interactive demonstration."""
from copy import deepcopy


def expand_demo(base: dict) -> dict:
    """Keep the acceptance examples intact and add source-backed fictional records."""
    if base['dataset']['id'] != 'demo:atlas-v1' or not base['dataset']['synthetic']:
        raise ValueError('Only the original synthetic demonstration can be expanded.')
    bundle = deepcopy(base)
    bundle['dataset']['id'] = 'demo:atlas-constellation-v2'
    bundle['dataset']['description'] += ' Extended with deterministic fictional research networks for the 3D explorer.'
    source = 'demo:source-constellation'
    bundle['sources'].append(dict(id=source, title='Synthetic research network examples',
        url='https://example.org/atlas-fixture/constellation', published_at='2026-10-03',
        retrieved_at='2026-10-03', kind='fixture', synthetic=True,
        license='CC0-1.0; fictional software fixture'))

    def node(group, kind, index, label):
        ident = f'demo:constellation-{group}-{kind.lower()}-{index}'
        bundle['nodes'].append(dict(id=ident, type=kind, label=label + ' (fictional)',
            aliases=[], properties={'description': 'Invented software demonstration record. Not medical evidence.',
                                     'demo_community': group}))
        return ident

    def link(a, predicate, b):
        ident = f'demo:constellation-claim-{len(bundle["claims"])}'
        bundle['claims'].append(dict(id=ident, subject=a, predicate=predicate, object=b,
            assertion_type='reported', context={}, extraction_confidence=None))
        bundle['evidence'].append(dict(id=ident.replace('claim', 'evidence'), claim_id=ident,
            source_id=source, locator=f'Generated fixture record {ident}',
            excerpt=f'FICTIONAL DEMONSTRATION: {a} — {predicate} → {b}. This relationship was invented for software demonstration and is not medical evidence.',
            stance='supports', review_status='unreviewed'))

    communities = []
    names = ['Aster', 'Bracken', 'Cobalt', 'Dune', 'Ember', 'Fable', 'Grove', 'Harbor',
             'Iris', 'Juniper', 'Kestrel', 'Lumen', 'Moss', 'Nimbus', 'Opal', 'Pollen']
    sizes = [110, 174, 132, 198, 96, 162, 128, 184, 142, 108, 176, 154, 122, 168, 138, 140]
    for i, name in enumerate(names):
        first_node = len(bundle['nodes'])
        disease = node(i, 'Disease', 0, f'{name} syndrome')
        mechanism = node(i, 'Mechanism', 0, f'{name} cellular pathway')
        genes = [node(i, 'Gene', j, f'{name.upper()}-{j+1}') for j in range(3)]
        variants = [node(i, 'Variant', j, f'{name} variant {j+1}') for j in range(8)]
        traits = [node(i, 'Phenotype', j, f'{name} trait {j+1}') for j in range(6)]
        org = node(i, 'Organization', 0, f'{name} research network')
        people = [node(i, 'Person', j, f'{name} investigator {j+1}') for j in range(2)]
        assets = [node(i, 'Asset', j, f'{name} {title}') for j, title in enumerate(['cell collection', 'registry'])]
        studies = [node(i, 'Study', j, f'{name} study {j+1}') for j in range(2)]
        papers = [node(i, 'Publication', j, f'{name} research note {j+1}') for j in range(2)]
        link(disease, 'INVOLVES', mechanism)
        for j, variant in enumerate(variants):
            link(disease, 'HAS_VARIANT', variant)
            link(variant, 'AFFECTS', genes[j % len(genes)])
            link(variant, 'HAS_EFFECT', mechanism)
        for trait in traits:
            link(disease, 'HAS_PHENOTYPE', trait)
        for j in range(1, len(traits)):
            link(traits[j], 'IS_A', traits[0])
        link(org, 'REPRESENTS', disease)
        for j in range(2):
            link(people[j], 'AFFILIATED_WITH', org)
            link(people[j], 'STUDIES', disease)
            link(people[j], 'AUTHORED', papers[j])
            link(org, 'MAINTAINS', assets[j])
            link(assets[j], 'RELEVANT_TO', disease)
            link(assets[j], 'USED_IN', studies[j])
            link(studies[j], 'STUDIES', mechanism)
        # Unequal research branches make dense neighborhoods, not identical hubs.
        branch = 0
        while len(bundle['nodes']) - first_node + 8 <= sizes[i]:
            index = 100 + branch
            pathway = node(i, 'Mechanism', index, f'{name} pathway {branch+2}')
            gene = node(i, 'Gene', index, f'{name.upper()}-{branch+4}')
            trait = node(i, 'Phenotype', index, f'{name} trait {branch+7}')
            person = node(i, 'Person', index, f'{name} investigator {branch+3}')
            study = node(i, 'Study', index, f'{name} study {branch+3}')
            paper = node(i, 'Publication', index, f'{name} research note {branch+3}')
            for k in range(2):
                variant = node(i, 'Variant', 100 + branch*2+k, f'{name} variant {branch*2+k+9}')
                link(variant, 'AFFECTS', gene)
                link(variant, 'HAS_EFFECT', pathway)
                if k == 0 or branch % 3 == 0:
                    link(disease, 'HAS_VARIANT', variant)
            link(disease, 'INVOLVES', pathway)
            link(disease, 'HAS_PHENOTYPE', trait)
            link(trait, 'IS_A', traits[branch % len(traits)])
            link(person, 'AUTHORED', paper)
            link(person, 'STUDIES', pathway)
            link(person, 'AFFILIATED_WITH', org)
            link(study, 'STUDIES', pathway)
            link(assets[branch % len(assets)], 'USED_IN', study)
            if branch % 3 == 0:
                link(study, 'STUDIES', mechanism)
            branch += 1
        for j in range(sizes[i] - (len(bundle['nodes']) - first_node)):
            variant = node(i, 'Variant', 1000+j, f'{name} rare variant {j+1}')
            link(variant, 'AFFECTS', genes[j % len(genes)])
            link(variant, 'HAS_EFFECT', mechanism)
        communities.append((disease, mechanism, assets, studies, traits))
    # A few shared assets and traits connect the otherwise local research neighborhoods.
    for i, (disease, mechanism, assets, studies, traits) in enumerate(communities):
        adjacent = communities[(i+1) % len(communities)]
        link(assets[0], 'RELEVANT_TO', adjacent[0])
        link(studies[0], 'STUDIES', adjacent[1])
        link(disease, 'HAS_PHENOTYPE', adjacent[4][0])
    return bundle
