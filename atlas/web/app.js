(() => {
  "use strict";

  const workspace = document.querySelector("#workspace");
  const input = document.querySelector("#search-input");
  const searchForm = document.querySelector("#search-form");
  const searchResults = document.querySelector("#search-results");
  const notice = document.querySelector("#notice");
  const evidenceDialog = document.querySelector("#evidence-dialog");
  const evidenceContent = document.querySelector("#evidence-content");
  let bundle = null;
  let activeSearch = -1;
  let debounceTimer = null;
  let searchRequestCounter = 0;
  let currentDisease = null;
  let currentResult = null;
  let selectedCandidate = null;
  let detailTab = "map";
  let explorationRequest = 0;
  let evidenceRequest = 0;
  let activeView = "explore";

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const append = (parent, ...children) => children.forEach((child) => child && parent.append(child));
  const values = (value) => Array.isArray(value) ? value : (value == null || value === "" ? [] : [value]);
  const textValue = (value, fallback = "") => typeof value === "string" || typeof value === "number" ? String(value) : fallback;
  const propertiesOf = (item) => item && typeof item.properties === "object" && item.properties ? item.properties : {};
  const descriptionOf = (item) => item?.description || item?.summary || propertiesOf(item).description || "";
  const labelOf = (item) => {
    if (typeof item === "string") {
      const found = bundle?.nodes?.find((node) => node.id === item);
      return found ? labelOf(found) : item;
    }
    return textValue(item?.label || item?.name || item?.symbol || item?.id, "Unlabelled entity");
  };
  const idOf = (item) => typeof item === "string" ? item : textValue(item?.id);
  const typeOf = (item) => textValue(item?.type || item?.kind, "Entity").replaceAll("_", " ");
  const compact = (value, limit = 180) => {
    const text = textValue(value).trim();
    if (text.length <= limit) return text;
    return `${text.slice(0, limit - 1).trimEnd()}…`;
  };
  const readableCode = (value) => {
    const known = {
      reported_mechanism_paths_have_supporting_evidence_and_matching_effect: "Reported mechanism paths have supporting evidence and matching effect context.",
      opposite_effect_contexts_disqualify_shared_mechanism: "The variant effects differ. This mechanism does not support a shared research route.",
      mechanistic_evidence_requires_review: "The supporting evidence still needs review.",
      effect_context_missing_or_unknown_requires_review: "The effect context is missing or uncertain, so this lead needs review.",
      biological_context_differs_or_is_incomplete: "Biological context differs or is incomplete.",
      mechanistic_path_has_contradicting_evidence: "Contradicting evidence affects the proposed mechanism path.",
      negative_assertion_is_not_positive_mechanism_evidence: "A negative assertion cannot support a positive mechanism connection.",
      mechanistic_path_lacks_reported_supported_evidence: "The mechanism path lacks reported, supported evidence.",
      phenotype_overlap_alone_is_insufficient_without_a_supported_shared_mechanism: "Phenotype overlap alone is insufficient without a supported shared mechanism.",
      shared_phenotypes_are_context_only_and_do_not_establish_mechanism: "Shared phenotypes provide context but do not establish a shared mechanism.",
      asset_has_reported_supported_contraindication_for_source_or_candidate_disease: "A reported, supported contraindication excludes this asset for the source or candidate disease.",
    };
    const raw = textValue(value);
    if (known[raw]) return known[raw];
    return raw.replace(/^([a-z_]+):/, (_, code) => `${code.replaceAll("_", " ")} · `).replaceAll("_", " ");
  };
  const claimLabel = (claim) => {
    const subject = bundle?.nodes?.find((node) => node.id === claim.subject);
    const object = bundle?.nodes?.find((node) => node.id === claim.object);
    const predicate = textValue(claim.predicate, "RELATES_TO").toLowerCase().replaceAll("_", " ");
    return `${labelOf(subject || claim.subject)} ${predicate} ${labelOf(object || claim.object)}`;
  };
  const list = (items, fallback) => {
    const normalized = values(items).filter((item) => item !== null && item !== undefined && item !== "");
    return normalized.length ? normalized : (fallback ? [fallback] : []);
  };
  const noticeText = (message, tone = "") => {
    notice.textContent = message;
    notice.className = tone ? `notice ${tone}` : "notice";
    notice.hidden = !message;
  };
  const hideSearch = () => {
    searchRequestCounter += 1;
    searchResults.hidden = true;
    searchResults.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    activeSearch = -1;
  };
  const showLoading = (label = "Following the evidence…") => {
    const state = el("div", "loading-state");
    append(state, el("span", "spinner"), el("span", "", label));
    workspace.replaceChildren(state);
  };

  function pill(text, tone = "") {
    return el("span", `pill${tone ? ` pill--${tone}` : ""}`, text);
  }

  function sectionHeading(kicker, title, aside = "") {
    const header = el("div", "section-heading");
    const copy = el("div");
    append(copy, el("h2", "", title));
    append(header, copy);
    if (aside) header.append(el("span", "section-aside", aside));
    return header;
  }

  function setView(name) {
    activeView=name;
    document.querySelectorAll("[data-view]").forEach(button => {
      if (button.dataset.view === name) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    document.title = `Atlas — ${{explore:"Explore",assets:"Research assets",sources:"Sources"}[name] || "Explore"}`;
    noticeText("");
  }

  function diseaseIndexRecord(disease) {
    const direct=bundle.claims.filter(c=>c.subject===disease.id);
    const variants=new Set(direct.filter(c=>c.predicate==="HAS_VARIANT").map(c=>c.object));
    const effects=bundle.claims.filter(c=>variants.has(c.subject) && c.predicate==="HAS_EFFECT");
    const mechanisms=[...direct.filter(c=>c.predicate==="INVOLVES"),...effects];
    const ids=new Set([...direct,...effects].map(c=>c.id));
    const evidence=bundle.evidence.filter(e=>ids.has(e.claim_id));
    const knownEffects=[...new Set(mechanisms.map(c=>c.context?.effect || "unknown"))];
    const inferred=mechanisms.length>0 && mechanisms.every(c=>c.assertion_type==="inferred");
    const conflict=evidence.some(e=>e.stance==="contradicts");
    const effect=knownEffects.length===1 ? knownEffects[0] : knownEffects.length ? "mixed" : "missing";
    const effectLabels={loss_of_function:"Loss of function",gain_of_function:"Gain of function",unknown:"Not established",mixed:"Mixed contexts",missing:"Not recorded"};
    const nodes=[...new Set(mechanisms.map(c=>c.object))].map(id=>bundle.nodes.find(n=>n.id===id)).filter(Boolean);
    return {nodes,evidence,inferred,conflict,effect:effectLabels[effect] || readableCode(effect),effectUnknown:effect==="unknown" || effect==="missing"};
  }

  function renderHome() {
    input.value="";
    hideSearch();
    explorationRequest++;
    currentDisease = null;
    currentResult = null;
    setView("explore");
    const diseases=(bundle?.nodes || []).filter(n=>n.type==="Disease").sort((a,b)=>a.label.localeCompare(b.label));
    const intro=el("header","index-intro");
    const copy=el("div","index-intro-copy");
    const title=el("h1");
    append(title,el("span","","Rare diseases."),el("span","","Connected research."));
    append(copy,el("p","collection-label","The rare disease atlas"),title,el("p","index-description","Trace shared biology, inspect the evidence, and find research assets worth investigating."));
    const actions=el("div","intro-actions");
    const start=el("button","intro-primary","Explore the atlas");start.type="button";start.dataset.index="true";
    const arrow=el("span","","↗");arrow.setAttribute("aria-hidden","true");start.append(arrow);
    const guide=el("button","intro-guide","How it works");guide.type="button";guide.dataset.guide="true";
    append(actions,start,guide);copy.append(actions);
    const figure=el("figure","intro-figure");
    const illustration=el("img","intro-art");illustration.src="/images/connected-biology.png";
    illustration.alt="Conceptual illustration of green, branching cellular forms connecting across an ivory background.";
    illustration.width=1448;illustration.height=1086;illustration.fetchPriority="high";
    const artCaption=el("figcaption","intro-caption");
    append(artCaption,el("span","","Biology is connected. Research can be, too."),el("span","illustration-note","Conceptual illustration"));
    append(figure,illustration,artCaption);append(intro,copy,figure);
    const section=el("section","disease-directory");
    section.id="disease-index";section.tabIndex=-1;section.setAttribute("aria-labelledby","index-title");
    const toolbar=el("div","index-toolbar");
    const heading=el("div","index-heading");append(heading,el("h2","","Disease index"),el("span","record-total",String(diseases.length).padStart(2,"0")));
    heading.querySelector("h2").id="index-title";
    const order=el("span","index-order","Select a disease to explore");append(toolbar,heading,order);section.append(toolbar);
    const table=el("table","disease-table");
    const caption=el("caption","sr-only","Disease index. Recorded mechanisms and effects describe source assertions, not clinical compatibility.");table.append(caption);
    const head=el("thead");const labels=el("tr");
    [["Disease","disease-col"],["Recorded mechanism","mechanism-col"],["Recorded effect","effect-col"],["Evidence records","evidence-col"],["","arrow-col"]].forEach(([label,cls])=>{const th=el("th",cls,label);th.scope="col";labels.append(th);});head.append(labels);table.append(head);
    const body=el("tbody");
    diseases.forEach(disease=>{
      const record=diseaseIndexRecord(disease);
      const row=el("tr","disease-row");row.dataset.explore=disease.id;
      const identity=el("td","disease-col");
      const button=el("button","disease-open");button.type="button";button.dataset.explore=disease.id;
      append(button,el("strong","",disease.label),el("span","disease-alias",disease.aliases.join(" · ") || disease.id));identity.append(button);
      const mechanism=el("td","mechanism-col");
      const names=record.nodes.map(n=>n.label.replace(" (fictional)",""));
      const name=el("span","mechanism-name",names.join("; ") || "Not recorded");name.title=record.nodes.map(n=>n.label).join("; ");mechanism.append(name);
      if(record.inferred)mechanism.append(el("span","record-note","Proposed mechanism"));
      const effect=el("td","effect-col");effect.append(el("span",record.effectUnknown ? "effect-value is-unknown" : "effect-value",record.effect));
      if(record.conflict)effect.append(el("span","record-note is-conflict","Conflicting evidence"));
      else if(record.inferred)effect.append(el("span","record-note is-unknown","Hypothesis only"));
      const count=el("td","evidence-col");count.append(el("span","record-count",String(record.evidence.length).padStart(2,"0")));
      const arrow=el("td","arrow-col");const mark=el("span","row-arrow","↗");mark.setAttribute("aria-hidden","true");arrow.append(mark);
      append(row,identity,mechanism,effect,count,arrow);body.append(row);
    });
    table.append(body);section.append(table);
    if(!diseases.length)section.append(el("p","empty-state","No disease records have been added to this atlas yet."));
    const note=el("div","index-note");
    append(note,el("p","","The index shows recorded assertions. A shared mechanism is a starting point for review, not evidence that an asset or treatment transfers between diseases."));
    const sources=el("button","text-link","Inspect the sources ↗");sources.type="button";sources.dataset.view="sources";note.append(sources);
    workspace.replaceChildren(intro,section,note);
  }

  function renderLibrary(kind) {
    explorationRequest++;
    hideSearch();
    setView(kind);
    const section=el("section","library-page");
    const isSources=kind==="sources";
    const records=isSources ? bundle?.sources || [] : (bundle?.nodes || []).filter(n=>n.type==="Asset");
    append(section,sectionHeading("RESEARCH LIBRARY",isSources ? "Sources" : "Research assets",`${records.length} record${records.length===1 ? "" : "s"}`),el("p","section-intro",isSources ? "The material behind the map, with retrieval dates and reuse terms." : "Existing resources to investigate, with evidence of relevance and ownership."));
    const rows=el("div","library-list");
    records.forEach(record=>{
      if(isSources) rows.append(sourceCard(record));
      else {
        const button=el("button","asset-library-row");button.type="button";button.dataset.entity=record.id;
        append(button,el("span","asset-library-icon","▤"),el("strong","",record.label),el("span","row-arrow","↗"));rows.append(button);
      }
    });
    if(!records.length) rows.append(el("p","empty-state","No records of this type have been added yet."));
    section.append(rows);workspace.replaceChildren(section);
  }

  function renderSearchResults(response) {
    currentResult=null;
    setView("explore");
    hideSearch();
    const section = el("section", "search-page");
    const heading = sectionHeading("SEARCH RESULTS", `Matches for “${response.query}”`, `${response.total} result${response.total === 1 ? "" : "s"}`);
    const intro = el("p", "section-intro", "Select a disease to explore its route, or open another entity to see where it appears in the map.");
    const results = el("div", "result-list");
    if (!response.results.length) {
      const empty = el("div", "empty-state");
      append(empty, el("span", "empty-icon", "⌕"), el("h3", "", "No matching entity"), el("p", "", "Try a shorter name, a known synonym, or part of an identifier."));
      results.append(empty);
    } else {
      response.results.forEach((node) => {
        const button = el("button", "result-row");
        button.type = "button";
        const kind = el("span", "result-kind", typeOf(node));
        const main = el("span", "result-main");
        append(main, el("strong", "", labelOf(node)), el("span", "result-summary", compact(descriptionOf(node) || node.id, 145)));
        const aliasList = list(node.aliases || node.synonyms).slice(0, 2).map((alias) => el("span", "alias-tag", textValue(alias)));
        const meta = el("span", "result-meta");
        append(meta, ...aliasList, el("span", "result-arrow", "→"));
        button.dataset.explore = idOf(node);
        if (typeOf(node).toLowerCase() !== "disease") button.dataset.entity = idOf(node);
        append(button, kind, main, meta);
        results.append(button);
      });
    }
    append(section, heading, intro, results);
    workspace.replaceChildren(section);
    workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderEntity(node) {
    explorationRequest++;
    const page = el("section", "entity-page");
    const back = el("button", "back-button", "← Back to atlas");
    back.type = "button";
    if(currentResult && activeView==="explore") { back.dataset.return = "true"; back.textContent="← Back to connection"; }
    else if(activeView==="assets") { back.dataset.view="assets"; back.textContent="← Research assets"; }
    else back.dataset.home = "true";
    const card = el("article", "entity-card");
    const top = el("div", "entity-topline");
    append(top, pill(typeOf(node), "teal"), el("span", "entity-id", idOf(node)));
    const heading = el("h2", "entity-title", labelOf(node));
    const description = el("p", "entity-description", textValue(descriptionOf(node), "No description has been entered for this entity."));
    append(card, top, heading, description);
    const aliases = list(node.aliases || node.synonyms);
    if (aliases.length) {
      const aliasLine = el("div", "entity-aliases");
      append(aliasLine, el("span", "detail-label", "ALSO KNOWN AS"), el("span", "", aliases.map((item) => textValue(item)).join(" · ")));
      card.append(aliasLine);
    }
    const related = (bundle?.claims || []).filter((claim) => claim.subject === idOf(node) || claim.object === idOf(node));
    const claimsPanel = el("div", "claim-list-panel");
    append(claimsPanel, el("p", "section-kicker", "LINKED CLAIMS"), el("h3", "", related.length ? "Evidence records in this map" : "No linked claim records"));
    related.forEach((claim) => claimsPanel.append(claimButton(claim)));
    if (!related.length) claimsPanel.append(el("p", "muted-copy", "This node is present in the map, but no claim record currently references it."));
    append(page, back, card, claimsPanel);
    workspace.replaceChildren(page);
  }

  function statusTone(status) {
    const value = textValue(status).toLowerCase();
    if (value === "supported" || value === "supported_lead" || value === "supported_route" || value === "leads_found") return "positive";
    if (value.includes("review")) return "caution";
    if (value.includes("reject")) return "muted";
    return "neutral";
  }

  function bullets(items, emptyText) {
    const normalized = list(items);
    if (!normalized.length) return el("p", "muted-copy", emptyText);
    const ul = el("ul", "plain-list");
    normalized.forEach((item) => {
      const li = el("li", "", typeof item === "string" ? readableCode(item) : labelOf(item));
      ul.append(li);
    });
    return ul;
  }

  function nodeChips(items, tone = "") {
    const wrap = el("div", "chip-row");
    list(items).forEach((item) => {
      if (typeof item === "object" && item) {
        const chip = el("button", `entity-chip${tone ? ` entity-chip--${tone}` : ""}`, labelOf(item));
        chip.type = "button";
        chip.dataset.entity = idOf(item);
        chip.title = typeOf(item);
        wrap.append(chip);
      } else {
        wrap.append(pill(textValue(item), tone));
      }
    });
    return wrap;
  }

  function claimButton(claim) {
    const button = el("button", "claim-button");
    button.type = "button";
    button.dataset.claim = idOf(claim);
    append(button, el("span", "claim-mark", "↗"), el("span", "claim-copy", claimLabel(claim)), el("span", "claim-arrow", "Open"));
    return button;
  }

  function renderEvidenceLinks(ids, evidenceItems) {
    const section = el("div", "evidence-links");
    append(section, el("p", "detail-label", "TRACE THE CLAIMS"));
    const claimIds = new Set(values(ids).map((value) => typeof value === "string" ? value : idOf(value)));
    values(evidenceItems).forEach((item) => {
      if (typeof item === "string") claimIds.add(item);
      else if (item && typeof item === "object") {
        const claimId = item.claim_id || item.claimId || (item.id && bundle?.claims?.some((claim) => claim.id === item.id) ? item.id : null);
        if (claimId) claimIds.add(claimId);
      }
    });
    const rows = (bundle?.claims || []).filter((claim) => claimIds.has(idOf(claim)));
    if (!rows.length) {
      section.append(el("p", "muted-copy", "No claim record is attached to this lead yet."));
    } else {
      const wrap = el("div", "claim-links");
      rows.forEach((claim) => wrap.append(claimButton(claim)));
      section.append(wrap);
    }
    return section;
  }

  function candidateStatus(value) {
    return {supported_lead:"Supported lead",needs_review:"Needs review",rejected:"Not supported"}[value] || readableCode(value);
  }

  function candidateSelector(candidate,index) {
    const button=el("button",`candidate-selector${candidate.disease.id===selectedCandidate ? " is-selected" : ""}`);
    button.type="button";button.dataset.candidate=candidate.disease.id;
    button.setAttribute("aria-pressed",String(candidate.disease.id===selectedCandidate));
    const title=el("span","candidate-selector-title");append(title,el("strong","",candidate.disease.label),el("span","candidate-arrow","→"));
    append(button,title,pill(candidateStatus(candidate.status),statusTone(candidate.status)));
    return button;
  }

  function renderConnectionMap(candidate) {
    const section=el("section","connection-map-section");
    const assessments=list(candidate.path_assessments);
    const assessment=assessments.find(a=>a.status==="supported") || assessments.find(a=>a.status==="needs_review") || assessments[0];
    if(!assessment) {section.append(el("p","empty-state","No shared mechanism path is recorded. Phenotype overlap alone does not establish one."));return section;}
    const claims=bundle.claims.filter(c=>assessment.claim_ids.includes(c.id));
    const ns="http://www.w3.org/2000/svg";
    const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 820 360");svg.setAttribute("role","group");svg.setAttribute("aria-label","Biological connection. Select a relationship to inspect its evidence.");
    const make=(tag,attrs)=>{const e=document.createElementNS(ns,tag);Object.entries(attrs || {}).forEach(([k,v])=>e.setAttribute(k,v));return e;};
    const defs=make("defs");const marker=make("marker",{id:"edge-arrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:5,markerHeight:5,orient:"auto-start-reverse"});marker.append(make("path",{d:"M 0 0 L 10 5 L 0 10 z",fill:"context-stroke"}));defs.append(marker);svg.append(defs);
    const positions=new Map();
    const mechanism=assessment.mechanism;
    positions.set(mechanism.id,{x:578,y:150,w:210,h:68,node:mechanism});
    [currentResult.disease,candidate.disease].forEach((disease,index)=>{
      const y=index===0 ? 42 : 250;
      positions.set(disease.id,{x:24,y,w:207,h:68,node:disease});
      const variantLink=claims.find(c=>c.subject===disease.id && c.predicate==="HAS_VARIANT");
      if(variantLink){const variant=bundle.nodes.find(n=>n.id===variantLink.object);if(variant) positions.set(variant.id,{x:292,y,w:192,h:68,node:variant});}
    });
    claims.forEach(claim=>{
      const a=positions.get(claim.subject),b=positions.get(claim.object);if(!a || !b)return;
      const x1=a.x+a.w,y1=a.y+a.h/2,x2=b.x,y2=b.y+b.h/2;
      const contradicted=bundle.evidence.some(e=>e.claim_id===claim.id && e.stance==="contradicts");
      const tone=contradicted ? "conflict" : (claim.assertion_type==="inferred" ? "inferred" : "reported");
      const path=make("path",{d:`M ${x1} ${y1} C ${x1+50} ${y1}, ${x2-48} ${y2}, ${x2} ${y2}`,class:`map-edge ${tone}`,"marker-end":"url(#edge-arrow)"});svg.append(path);
      const isEffect=claim.predicate==="HAS_EFFECT" || claim.predicate==="INVOLVES";
      const label=isEffect ? (claim.context.effect || "unknown effect").replaceAll("_"," ") : "has variant";
      const lx=isEffect ? 552 : 261,ly=isEffect ? (a.y<150 ? 119 : 246) : y1-17;
      const group=make("g",{class:`edge-label ${tone}`,"data-claim":claim.id,role:"button",tabindex:0,"aria-label":`${claimLabel(claim)}: ${label}. Inspect evidence`});
      const title=make("title");title.textContent=claimLabel(claim);group.append(title);
      group.append(make("rect",{x:lx-(isEffect ? 75 : 41),y:ly-13,width:isEffect ? 150 : 82,height:25,rx:2}));
      const text=make("text",{x:lx,y:ly+4,"text-anchor":"middle"});text.textContent=label;group.append(text);svg.append(group);
    });
    positions.forEach(({x,y,w,h,node})=>{
      const group=make("g",{class:`map-node ${node.type.toLowerCase()}`,"data-entity":node.id,role:"button",tabindex:0,"aria-label":`${node.label}, ${node.type}. Open entity`});
      const title=make("title");title.textContent=node.label;group.append(title);
      group.append(make("rect",{x,y,width:w,height:h,rx:2}));
      const type=make("text",{x:x+14,y:y+22,class:"map-node-type"});type.textContent=node.type;group.append(type);
      const label=make("text",{x:x+14,y:y+46,class:"map-node-name"});label.textContent=compact(node.label.replace(" (fictional)",""),27);group.append(label);svg.append(group);
    });
    const canvas=el("div","map-canvas");canvas.append(svg);section.append(el("p","mobile-map-hint","Swipe the map to follow the complete path →"),canvas);
    const caption=el("div","map-caption");append(caption,el("span","","Select a relationship to inspect its evidence."),el("span","",assessment.status==="supported" ? "Reported biological path" : "Unconfirmed path · review limitations"));section.append(caption);
    if(assessments.length>1) section.append(el("p","muted-copy",`Showing one of ${assessments.length} recorded paths. All linked claims remain available in Evidence.`));
    return section;
  }

  function selectedClaimIds(candidate) {
    const ids=new Set(candidate?.path_claim_ids || []);
    (currentResult.opportunities || []).filter(o=>o.candidate_id===candidate?.disease.id).forEach(o=>(o.path_claim_ids || []).forEach(id=>ids.add(id)));
    return ids;
  }

  function renderClaimTable(candidate) {
    const section=el("div","evidence-table");
    const claims=bundle.claims.filter(c=>selectedClaimIds(candidate).has(c.id));
    section.append(el("p","section-intro",`${claims.length} linked claims. Open a row to compare the exact source excerpts and biological context.`));
    claims.forEach(claim=>{
      const button=claimButton(claim);
      const rows=bundle.evidence.filter(e=>e.claim_id===claim.id);
      const meta=el("span","claim-table-meta");
      const conflicting=rows.filter(e=>e.stance==="contradicts").length;
      append(meta,pill(claim.assertion_type,claim.assertion_type==="inferred" ? "caution" : "neutral"),el("span","",`${rows.filter(e=>e.stance==="supports").length} supporting`));
      if(conflicting)meta.append(pill(`${conflicting} conflicting`,"conflict"));
      if(!rows.length)meta.append(pill("No evidence","caution"));
      button.insertBefore(meta,button.lastChild);section.append(button);
    });
    return section;
  }

  function renderOpportunity(opportunity, candidates) {
    const card = el("article", "opportunity-card");
    const top = el("div", "opportunity-top");
    const title = el("div");
    append(title, el("p", "section-kicker", "A PLACE TO START"), el("h3", "", opportunity.asset ? labelOf(opportunity.asset) : "Research opportunity"));
    append(top, el("span", "opportunity-icon", "↗"), title);
    card.append(top);
    if(opportunity.proposal) card.append(el("p","opportunity-proposal",opportunity.proposal));
    if (opportunity.status) card.append(pill(textValue(opportunity.status).replaceAll("_", " "), statusTone(opportunity.status)));
    if (opportunity.asset) {
      const asset = el("div", "asset-row");
      append(asset, el("span", "detail-label", "EXISTING ASSET"), el("button", "asset-button", labelOf(opportunity.asset)));
      asset.querySelector("button").type = "button";
      asset.querySelector("button").dataset.entity = idOf(opportunity.asset);
      const candidate = candidates.find((item) => idOf(item.disease) === textValue(opportunity.candidate_id));
      if (candidate?.disease) asset.append(el("span", "asset-connector", `Potentially relevant to ${labelOf(candidate.disease)}`));
      card.append(asset);
    }
    const people = el("div", "opportunity-groups");
    const orgs = el("div", "context-group");
    append(orgs, el("span", "detail-label", "ORGANIZATIONS"), nodeChips(opportunity.organizations));
    const collaborators = el("div", "context-group");
    append(collaborators, el("span", "detail-label", "RESEARCH CONTACTS"), nodeChips(opportunity.collaborators));
    append(people, orgs, collaborators);
    card.append(people);
    if (opportunity.next_step) {
      const next = el("div", "next-step");
      append(next, el("span", "next-step-number", "NEXT"), el("p", "", opportunity.next_step));
      card.append(next);
    }
    const questions = list(opportunity.validation_questions);
    if (questions.length) {
      append(card, el("span", "detail-label", "VALIDATE BEFORE ACTING"), bullets(questions, ""));
    }
    if (opportunity.reuse_scope) {
      const reuse = el("p", "reuse-note");
      append(reuse, el("strong", "", "Reuse scope · "), document.createTextNode(textValue(opportunity.reuse_scope)));
      card.append(reuse);
    }
    if (list(opportunity.differences).length) {
      const diff = el("p", "difference-note");
      append(diff, el("strong", "", "Limits · "), document.createTextNode(list(opportunity.differences).map((item) => typeof item === "string" ? readableCode(item) : labelOf(item)).join("; ")));
      card.append(diff);
    }
    card.append(renderEvidenceLinks(opportunity.path_claim_ids, opportunity.evidence));
    return card;
  }

  function renderNoRoute(result) {
    const section = el("section", "no-route-card");
    const symbol = el("span", "no-route-symbol", "···");
    symbol.setAttribute("aria-hidden", "true");
    append(section, symbol, el("span", "card-type", "NO SUPPORTED ROUTE FOUND"), el("h2", "", "The map stops here for now."), el("p", "no-route-lede", "Atlas has not found a supported route from this disease in the current dataset. That is a coverage gap, not evidence that no connection exists."));
    const gaps = list(result.gaps);
    const questions = list(result.next_questions);
    const columns = el("div", "gap-columns");
    const gapPanel = el("div", "gap-panel");
    append(gapPanel, el("span", "detail-label", "WHAT IS MISSING"), bullets(gaps, "No specific evidence gap was returned."));
    const questionPanel = el("div", "gap-panel gap-panel--question");
    append(questionPanel, el("span", "detail-label", "WHAT COULD CHANGE THIS"), bullets(questions, "Add evidence or search another name to expand the map."));
    append(columns, gapPanel, questionPanel);
    section.append(columns);
    const coverage = result.coverage;
    if (Array.isArray(coverage) && coverage.length) {
      const coverageRows = coverage.map((record) => `${textValue(record.source_id, "source")}: ${textValue(record.status, "unknown")} · ${textValue(record.scope, "scope unspecified")}`);
      section.append(el("p", "coverage-line", `Dataset coverage · ${coverageRows.join(" / ")}`));
    } else if (coverage && typeof coverage === "object" && !Array.isArray(coverage)) {
      section.append(el("p", "coverage-line", `Dataset coverage · ${Object.entries(coverage).map(([key, value]) => `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" / ")}`));
    } else if (coverage) {
      section.append(el("p", "coverage-line", `Dataset coverage · ${textValue(coverage)}`));
    }
    return section;
  }

  function renderExplore(result, candidateId = null, tab = "map") {
    currentDisease=result.disease;currentResult=result;detailTab=tab;
    setView("explore");
    const candidates=list(result.candidates);
    const selected=candidates.find(c=>c.disease.id===candidateId) || candidates.find(c=>c.status==="supported_lead") || candidates[0];
    selectedCandidate=selected?.disease.id || null;
    const page=el("section","explore-page");
    const breadcrumb=el("button","back-button","← All diseases");breadcrumb.type="button";breadcrumb.dataset.home="true";
    const heading=el("div","disease-heading");
    const copy=el("div");append(copy,el("h1","",result.disease.label),el("p","disease-description",descriptionOf(result.disease)));
    const meta=el("div","disease-meta");append(meta,pill(result.status==="leads_found" ? "Research route found" : "No supported route",statusTone(result.status)),el("span","entity-id",result.disease.id));
    append(heading,copy,meta);append(page,breadcrumb,heading);
    if(result.status==="no_supported_route") {
      const gap=renderNoRoute(result);page.append(gap);
    }
    if(selected) {
      const shell=el("div","research-workbench");
      const aside=el("aside","candidate-rail");
      append(aside,el("h2","","Connections"),el("p","rail-note",`${candidates.length} candidates examined`));
      const listWrap=el("div","candidate-selectors");candidates.forEach((c,i)=>listWrap.append(candidateSelector(c,i)));aside.append(listWrap);
      const note=el("details","ranking-details");note.append(el("summary","","How these are ordered"),el("p","",result.ranking_note));aside.append(note);
      const main=el("div","connection-detail");
      const detailHead=el("div","connection-heading");
      const identity=el("div");append(identity,el("p","connection-label","Connection under review"),el("h2","",selected.disease.label));append(detailHead,identity,pill(candidateStatus(selected.status),statusTone(selected.status)));main.append(detailHead);
      const tabs=el("div","detail-tabs");tabs.setAttribute("role","tablist");tabs.setAttribute("aria-label","Connection details");
      [["map","Connection map"],["evidence","Evidence"],["assets","Research assets"]].forEach(([key,label])=>{
        const button=el("button",key===tab ? "active" : "",label);button.type="button";button.dataset.tab=key;button.id=`tab-${key}`;button.setAttribute("role","tab");button.setAttribute("aria-selected",String(key===tab));button.setAttribute("aria-controls","connection-panel");button.tabIndex=key===tab ? 0 : -1;tabs.append(button);
      });main.append(tabs);
      const panel=el("div","connection-panel");panel.id="connection-panel";panel.setAttribute("role","tabpanel");panel.setAttribute("aria-labelledby",`tab-${tab}`);
      if(tab==="map") {
        panel.append(renderConnectionMap(selected));
        const assessment=el("div",`assessment assessment--${statusTone(selected.status)}`);
        append(assessment,el("h3","",selected.status==="supported_lead" ? "Basis for this connection" : selected.status==="needs_review" ? "Requires review" : "Why this route is not supported"),bullets(selected.reasons,"No explanation supplied."));
        if(selected.differences?.length)append(assessment,el("h4","","Context differences"),bullets(selected.differences,""));
        panel.append(assessment);
        const related=(result.opportunities || []).filter(o=>o.candidate_id===selected.disease.id);
        const next=el("div","asset-preview");
        if(related.length) {
          const intro=el("div");append(intro,el("span","detail-label","RESEARCH ASSET"),el("strong","",labelOf(related[0].asset)),el("span","",related[0].status==="supported_route" ? "Maintainer and supporting evidence available" : related[0].status==="rejected" ? "Excluded by the recorded evidence" : "Requires review before use"));
          const button=el("button","secondary-button","Review asset →");button.type="button";button.dataset.tab="assets";append(next,intro,button);
        } else append(next,el("p","","No evidenced asset-and-maintainer route is available for this connection."));
        panel.append(next);
      } else if(tab==="evidence") panel.append(renderClaimTable(selected));
      else {
        const opportunities=(result.opportunities || []).filter(o=>o.candidate_id===selected.disease.id);
        if(opportunities.length) opportunities.forEach(o=>panel.append(renderOpportunity(o,candidates)));
        else append(panel,el("div","empty-state","No shared research asset is supported by the current evidence."),bullets(result.next_questions,"Search additional sources or investigate a different candidate."));
      }
      main.append(panel);append(shell,aside,main);page.append(shell);
    }
    workspace.replaceChildren(page);
  }

  function safeHttpUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function sourceCard(source) {
    const card = el("article", "source-card");
    const title = textValue(source.title || source.name || source.label, "Untitled source");
    append(card, el("span", "detail-label", textValue(source.type || source.kind, "SOURCE")), el("h4", "", title));
    const locator = [source.locator, source.page, source.section, source.date].filter(Boolean).map((part) => textValue(part)).join(" · ");
    if (locator) card.append(el("p", "source-locator", locator));
    const metadata = [
      source.kind && `Type: ${source.kind}`,
      source.published_at && `Published: ${source.published_at}`,
      source.retrieved_at && `Retrieved: ${source.retrieved_at}`,
      source.version && `Version: ${source.version}`,
      source.license && `License: ${source.license}`,
    ].filter(Boolean);
    if (metadata.length) card.append(el("p", "source-metadata", metadata.join(" · ")));
    const url = safeHttpUrl(source.url || source.external_url);
    if (url) {
      const link = el("a", "source-link", "Open source ↗");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
    }
    return card;
  }

  function evidenceRow(item, contradiction = false) {
    const card = el("article", `evidence-record${contradiction ? " evidence-record--contradiction" : ""}`);
    const title = textValue(item.title || item.label, contradiction ? "Counter-evidence" : "Supporting evidence");
    const review = textValue(item.review_status).replaceAll("_", " ");
    append(card, el("span", "evidence-status", contradiction ? "COUNTER-EVIDENCE" : "SUPPORTING RECORD"), el("span", "review-tag", review || "review status unavailable"), el("h4", "", title));
    const source = bundle?.sources?.find((row) => row.id === item.source_id);
    if (source) card.append(el("p", "source-attribution", `Source · ${textValue(source.title, "Untitled source")}`));
    if (item.locator) card.append(el("p", "source-locator", `Locator · ${textValue(item.locator)}`));
    const excerpt = textValue(item.excerpt || item.quote || item.text || item.summary);
    if (excerpt) {
      const quote = el("blockquote", "evidence-excerpt", excerpt);
      card.append(quote);
    }
    const context = textValue(item.context || item.note || item.interpretation);
    if (context) card.append(el("p", "source-context", context));
    const confidence = item.extraction_confidence ?? item.confidence;
    if (confidence !== undefined && confidence !== null && confidence !== "") {
      const confidenceText = typeof confidence === "number" ? `${Math.round(confidence * (confidence <= 1 ? 100 : 1))}%` : String(confidence);
      const row = el("p", "confidence-line");
      append(row, el("strong", "", "Extraction confidence · "), document.createTextNode(`${confidenceText} · A measure of extraction quality, not clinical certainty.`));
      card.append(row);
    }
    return card;
  }

  async function openClaim(claimId) {
    const requestId=++evidenceRequest;
    evidenceContent.replaceChildren(el("div", "loading-state", "Loading source records…"));
    const claimTitle = document.querySelector("#evidence-title");
    claimTitle.textContent = "Claim details";
    if(!evidenceDialog.open)evidenceDialog.showModal();
    try {
      const response = await fetch(`/api/claim?id=${encodeURIComponent(claimId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || "This evidence record could not be loaded.");
      if(requestId!==evidenceRequest)return;
      const claim = data.claim || {};
      claimTitle.textContent = claimLabel(claim);
      evidenceContent.replaceChildren();
      if (claim.description) evidenceContent.append(el("p", "evidence-summary", claim.description));
      const meta = el("div", "evidence-meta");
      append(meta, pill(textValue(claim.assertion_type, "Claim"), claim.assertion_type==="inferred" ? "caution" : "neutral"), el("span", "entity-id", textValue(claim.id)));
      evidenceContent.append(meta);
      const context = claim.context && typeof claim.context === "object" ? claim.context : {};
      const contextEntries = Object.entries(context).filter(([, value]) => value !== null && value !== undefined && value !== "");
      const claimContext = el("div", "claim-context");
      const confidence = claim.extraction_confidence;
      const confidenceText = typeof confidence === "number" ? `${Math.round(confidence * 100)}%` : "Not recorded";
      const summaryParts = [`Assertion · ${textValue(claim.assertion_type, "unknown")}`, `Extraction confidence · ${confidenceText}`];
      if (contextEntries.length) summaryParts.push(...contextEntries.map(([key, value]) => `${key.replaceAll("_", " ")} · ${typeof value === "boolean" ? (value ? "yes" : "no") : String(value).replaceAll("_", " ")}`));
      append(claimContext, el("span", "detail-label", "CLAIM CONTEXT"), el("p", "claim-context-copy", summaryParts.join("  /  ")), el("p", "confidence-note", "Extraction confidence measures how reliably a field was captured. It is not clinical certainty."));
      evidenceContent.append(claimContext);
      const supporting = list(data.support);
      const contradictions = list(data.contradictions);
      const sources = list(data.sources);
      const sections = el("div", "evidence-section");
      append(sections, el("p", "section-kicker", "SOURCE MATERIAL"), el("h3", "", `${supporting.length} supporting · ${contradictions.length} counter-evidence`));
      const records = el("div", "evidence-records");
      supporting.forEach((item) => records.append(evidenceRow(item)));
      contradictions.forEach((item) => records.append(evidenceRow(item, true)));
      if (!supporting.length && !contradictions.length) records.append(el("p", "muted-copy", "No excerpts are linked to this claim yet."));
      sections.append(records);
      evidenceContent.append(sections);
      const sourceSection = el("div", "evidence-section");
      append(sourceSection, el("p", "section-kicker", "CITATIONS"), el("h3", "", "Sources and locators"));
      const sourceList = el("div", "source-list");
      sources.forEach((source) => sourceList.append(sourceCard(source)));
      if (!sources.length) sourceList.append(el("p", "muted-copy", "No source record is attached to this claim."));
      sourceSection.append(sourceList);
      evidenceContent.append(sourceSection);
      evidenceContent.append(el("p", "evidence-caveat", "Evidence supports a research question, not a clinical conclusion. Check the cited material and study context before relying on this claim."));
    } catch (error) {
      if(requestId!==evidenceRequest)return;
      evidenceContent.replaceChildren(el("p", "error-copy", error.message || "Evidence could not be loaded."));
    }
  }

  async function explore(id) {
    if (!id) return;
    hideSearch();
    const requestId=++explorationRequest;
    showLoading();
    try {
      const response = await fetch(`/api/explore?disease=${encodeURIComponent(id)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || "The atlas could not explore that disease.");
      if(requestId!==explorationRequest)return;
      renderExplore(data);
      window.scrollTo({top:0});
    } catch (error) {
      if(requestId!==explorationRequest)return;
      renderHome();
      noticeText(error.message || "The atlas could not complete this exploration.", "notice--error");
    }
  }

  async function search(query) {
    const term = query.trim();
    if (!term) {
      hideSearch();
      return;
    }
    const requestId = ++searchRequestCounter;
    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(term)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || "Search is unavailable.");
      if (requestId !== searchRequestCounter) return;
      renderSuggestions(data.results || []);
    } catch (error) {
      if (requestId !== searchRequestCounter) return;
      renderSuggestions([], error.message || "Search is unavailable.");
    }
  }

  function renderSuggestions(results, error = "") {
    searchResults.replaceChildren();
    activeSearch = -1;
    if (error) {
      searchResults.append(el("div", "search-empty", error));
    } else if (!results.length) {
      searchResults.append(el("div", "search-empty", "No match yet. Try another name or synonym."));
    } else {
      results.slice(0, 6).forEach((node, index) => {
        const button = el("button", "suggestion");
        button.type = "button";
        button.role = "option";
        button.dataset.suggestion = idOf(node);
        button.dataset.index = String(index);
        append(button, el("span", "suggestion-kind", typeOf(node)), el("strong", "", labelOf(node)), el("span", "suggestion-alias", compact(descriptionOf(node) || node.id, 80)));
        searchResults.append(button);
      });
    }
    searchResults.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function setActiveSuggestion(next) {
    const suggestions = [...searchResults.querySelectorAll("[data-suggestion]")];
    if (!suggestions.length) return;
    activeSearch = Math.max(0, Math.min(suggestions.length - 1, next));
    suggestions.forEach((button, index) => {
      button.classList.toggle("is-active", index === activeSearch);
      button.setAttribute("aria-selected", index === activeSearch ? "true" : "false");
    });
    suggestions[activeSearch].scrollIntoView({ block: "nearest" });
  }

  async function initialise() {
    try {
      const [healthResponse, statsResponse, graphResponse] = await Promise.all([
        fetch("/api/health"), fetch("/api/stats"), fetch("/api/graph"),
      ]);
      const [health, statsPayload, graph] = await Promise.all([healthResponse.json(), statsResponse.json(), graphResponse.json()]);
      if (!healthResponse.ok || !statsResponse.ok || !graphResponse.ok) throw new Error("The local dataset could not be opened.");
      bundle = graph;
      if (health.synthetic === true && graph.dataset?.synthetic === true) {
        document.querySelector("#demo-ribbon").hidden = false;
        document.querySelector("#dataset-title").textContent = "Fictional diseases, people, and sources. For interface exploration only.";
      }
      const nodes = Array.isArray(graph.nodes) ? graph.nodes.length : 0;

      document.querySelector("#footer-dataset").textContent = textValue(graph.dataset?.title, "A local, read-only research map");
      const entityTotal = statsPayload.stats?.nodes ?? statsPayload.stats?.node_count ?? nodes;
      input.title = `Search ${Number(entityTotal).toLocaleString()} mapped entities`;
      renderHome();
    } catch (error) {
      workspace.replaceChildren();
      noticeText(error.message || "The local dataset could not be opened.", "notice--error");
      const unavailable = el("div", "empty-state empty-state--large");
      append(unavailable, el("span", "empty-icon", "⌁"), el("h2", "", "Atlas is unavailable"), el("p", "", "Start the local atlas server and refresh this page to load its dataset."));
      workspace.append(unavailable);
    }
  }

  searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearTimeout(debounceTimer);
    searchRequestCounter += 1;
    const active = searchResults.querySelector(".suggestion.is-active");
    const term = input.value.trim();
    hideSearch();
    if (active) {
      const node = bundle?.nodes?.find((item) => item.id === active.dataset.suggestion);
      if (node && typeOf(node).toLowerCase() !== "disease") renderEntity(node);
      else explore(active.dataset.suggestion);
      return;
    }
    if (!term) return;
    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(term)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || "Search is unavailable.");
      renderSearchResults(data);
      if (data.total === 1 && typeOf(data.results[0]).toLowerCase() === "disease") explore(idOf(data.results[0]));
    } catch (error) {
      noticeText(error.message || "Search is unavailable.", "notice--error");
    }
  });

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    searchRequestCounter += 1;
    const term = input.value.trim();
    if (!term) {
      hideSearch();
      return;
    }
    debounceTimer = setTimeout(() => search(term), 160);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveSuggestion(activeSearch + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveSuggestion(activeSearch - 1);
    } else if (event.key === "Escape") {
      hideSearch();
    } else if (event.key === "Enter" && !searchResults.hidden) {
      const active = searchResults.querySelector(".suggestion.is-active");
      if (active) {
        event.preventDefault();
        const node = bundle?.nodes?.find((item) => item.id === active.dataset.suggestion);
        hideSearch();
        if (node && typeOf(node).toLowerCase() !== "disease") renderEntity(node);
        else explore(active.dataset.suggestion);
      }
    }
  });

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if(target.closest("[data-index]")) {
      const index=document.querySelector("#disease-index");
      index?.focus({preventScroll:true});index?.scrollIntoView({block:"start"});return;
    }
    if(target.closest("[data-guide]")) {document.querySelector("#method-dialog").showModal();return;}
    const view=target.closest("[data-view]");
    if(view) {hideSearch(); if(view.dataset.view==="explore")renderHome();else renderLibrary(view.dataset.view);window.scrollTo({top:0});return;}
    const returnButton=target.closest("[data-return]");
    if(returnButton && currentResult){renderExplore(currentResult,selectedCandidate,detailTab);return;}
    const candidate=target.closest("[data-candidate]");
    if(candidate && currentResult){renderExplore(currentResult,candidate.dataset.candidate,detailTab);workspace.querySelector(`[data-candidate="${CSS.escape(candidate.dataset.candidate)}"]`)?.focus({preventScroll:true});return;}
    const tabButton=target.closest("[data-tab]");
    if(tabButton && currentResult){renderExplore(currentResult,selectedCandidate,tabButton.dataset.tab);document.querySelector(`#tab-${tabButton.dataset.tab}`)?.focus({preventScroll:true});return;}
    const suggestion = target.closest("[data-suggestion]");
    if (suggestion) {
      const node = bundle?.nodes?.find((item) => item.id === suggestion.dataset.suggestion);
      input.value = labelOf(node || suggestion.dataset.suggestion);
      hideSearch();
      if (node && typeOf(node).toLowerCase() !== "disease") renderEntity(node);
      else explore(suggestion.dataset.suggestion);
      return;
    }
    const claim = target.closest("[data-claim]");
    if (claim) {
      openClaim(claim.dataset.claim);
      return;
    }
    const home = target.closest("[data-home]");
    if (home) {
      currentDisease = null;
      input.value = "";
      renderHome();
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const exploreButton = target.closest("[data-explore]");
    if (exploreButton) {
      const node = bundle?.nodes?.find((item) => item.id === exploreButton.dataset.explore);
      if (node && typeOf(node).toLowerCase() !== "disease") renderEntity(node);
      else explore(exploreButton.dataset.explore);
      return;
    }
    const entity = target.closest("[data-entity]");
    if (entity) {
      const node = bundle?.nodes?.find((item) => item.id === entity.dataset.entity);
      if (node) renderEntity(node);
      return;
    }
    if (!target.closest(".search-form")) hideSearch();
  });

  document.addEventListener("keydown",event=>{
    if(event.target.matches?.("svg [role=button]" ) && (event.key==="Enter" || event.key===" ")) {
      event.preventDefault();const claim=event.target.dataset.claim;
      if(claim)openClaim(claim);else {const node=bundle.nodes.find(n=>n.id===event.target.dataset.entity);if(node)renderEntity(node);}
    }
    if(event.target.getAttribute?.("role")==="tab" && ["ArrowLeft","ArrowRight","Home","End"].includes(event.key)){
      event.preventDefault();const keys=["map","evidence","assets"],i=keys.indexOf(detailTab);
      const next=event.key==="Home" ? 0 : event.key==="End" ? 2 : (i+(event.key==="ArrowRight" ? 1 : 2))%3;
      renderExplore(currentResult,selectedCandidate,keys[next]);document.querySelector(`#tab-${keys[next]}`).focus({preventScroll:true});
    }
  });

  document.querySelector("#method-button").addEventListener("click", () => document.querySelector("#method-dialog").showModal());
  document.querySelector("#close-method").addEventListener("click", () => document.querySelector("#method-dialog").close());
  document.querySelector("#close-evidence").addEventListener("click", () => evidenceDialog.close());
  document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  }));

  initialise();
})();
