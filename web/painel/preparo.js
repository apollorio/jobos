"use strict";
var JobosPreparo = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // D:/dev/_dev web/_rvalle-site/__VAGAS/_system/web/painel/src/preparo.ts
  var preparo_exports = {};
  __export(preparo_exports, {
    mount: () => mount
  });
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== void 0) node.textContent = text;
    return node;
  }
  function list(title, items) {
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
  function evidenceLine(ref) {
    const li = el("li", "");
    li.append(el("code", "", ref.pointer));
    const bits = [ref.label, ref.qualifier].filter((part) => part.length > 0).join(" · ");
    if (bits) li.append(el("span", "small muted", " " + bits));
    if (ref.profile_wording !== void 0) {
      li.append(el("p", "prep-wording", ref.profile_wording));
    }
    return li;
  }
  function mount(host, support) {
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
  return __toCommonJS(preparo_exports);
})();
