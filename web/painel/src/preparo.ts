interface EvidenceRef {
  pointer: string;
  label: string;
  qualifier: string;
  profile_wording?: string;
}

interface UseRow {
  text: string;
  status: string;
  explanation: string;
  evidence: EvidenceRef[];
}

interface GapRow {
  text: string;
  explanation: string;
  pointers: string[];
  boundary: boolean;
}

interface StoryRow {
  id: string;
  text: string;
  domains: string[];
}

interface HeadlineRow {
  id: string | null;
  headline_en: string;
  domains: string[];
  overlap: number;
}

interface SupportPacket {
  available: boolean;
  uses_ai: boolean;
  writes_cv: boolean;
  sends_application: boolean;
  limits: string;
  reason?: string;
  display_name?: string | null;
  one_liner?: string | null;
  decision?: string | null;
  headline?: HeadlineRow | null;
  headline_candidates?: HeadlineRow[];
  headline_rule?: string;
  use?: UseRow[];
  do_not_claim?: GapRow[];
  stories?: StoryRow[];
  unknowns?: string[];
  checklist?: string[];
  public_profile_url?: string;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function list(title: string, items: readonly string[]): HTMLElement {
  const block = el("div", "");
  block.append(el("h4", "", title));
  if (!items.length) {
    block.append(el("p", "muted", "Nenhum."));
    return block;
  }
  const ul = el("ul", "list-plain");
  for (const item of items) ul.append(el("li", "", item));
  block.append(ul);
  return block;
}

function evidenceLine(ref: EvidenceRef): HTMLElement {
  const li = el("li", "");
  li.append(el("code", "", ref.pointer));
  const bits = [ref.label, ref.qualifier].filter((part) => part.length > 0).join(" · ");
  if (bits) li.append(el("span", "small muted", " " + bits));
  if (ref.profile_wording !== undefined) {
    li.append(el("p", "prep-wording", ref.profile_wording));
  }
  return li;
}

function mount(host: HTMLElement, support: SupportPacket): void {
  host.append(el("p", "prep-limits", support.limits));
  if (!support.available) {
    host.append(el("p", "muted", support.reason ?? "Preparo indisponível."));
    host.append(list("Antes de decidir", support.checklist ?? []));
    return;
  }
  if (support.one_liner) host.append(el("p", "", support.one_liner));
  host.append(el("p", "muted", support.headline_rule ?? ""));
  if (support.headline) {
    host.append(el("p", "prep-headline", support.headline.headline_en));
  } else {
    const candidates = support.headline_candidates ?? [];
    const block = el("div", "");
    block.append(el("h4", "", "Headlines do perfil que cabem nesta vaga"));
    if (!candidates.length) block.append(el("p", "muted", "Nenhum."));
    else {
      const ul = el("ul", "list-plain");
      for (const row of candidates) ul.append(el("li", "", row.headline_en));
      block.append(ul);
    }
    host.append(block);
  }
  const useBlock = el("div", "");
  useBlock.append(el("h4", "", "O que o perfil sustenta"));
  const rows = support.use ?? [];
  if (!rows.length) useBlock.append(el("p", "muted", "Nenhum requisito atendido ou parcial."));
  else {
    const ul = el("ul", "list-plain");
    for (const row of rows) {
      const li = el("li", "");
      li.append(el("strong", "", row.text));
      if (row.explanation) li.append(el("p", "small muted", row.explanation));
      if (row.evidence.length) {
        const refs = el("ul", "list-bare");
        for (const ref of row.evidence) refs.append(evidenceLine(ref));
        li.append(refs);
      }
      ul.append(li);
    }
    useBlock.append(ul);
  }
  host.append(useBlock);
  const denied = support.do_not_claim ?? [];
  host.append(list("Não alegar", denied.map((row) => row.explanation ? `${row.text} — ${row.explanation}` : row.text)));
  const stories = el("div", "");
  stories.append(el("h4", "", "Histórias já escritas no perfil"));
  const bank = support.stories ?? [];
  if (!bank.length) stories.append(el("p", "muted", "Nenhuma história deste perfil cobre os domínios atendidos."));
  else {
    for (const story of bank) {
      const card = el("article", "prep-story");
      card.append(el("h5", "", story.id));
      card.append(el("p", "", story.text));
      stories.append(card);
    }
  }
  host.append(stories);
  host.append(list("Ainda desconhecido", support.unknowns ?? []));
  host.append(list("Checklist", support.checklist ?? []));
  if (support.public_profile_url) {
    host.append(el("p", "small muted", "Perfil público de comparação: " + support.public_profile_url + ". A autoridade desta página é a cópia local."));
  }
}

export { mount };
