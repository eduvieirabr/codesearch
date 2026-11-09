"use strict";
(() => {
  const payload = JSON.parse(document.getElementById("manual-data").textContent);
  const recordings = payload.recording.recordings;
  const catalog = new Map(payload.catalog.map(item => [item.name, item]));
  const cards = [...document.querySelectorAll(".tool-card")];
  const normalize = value => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const search = document.getElementById("tool-search");
  const group = document.getElementById("tool-group");
  const filterTools = () => {
    let count = 0;
    const words = normalize(search.value).trim().split(/\s+/).filter(Boolean);
    for (const card of cards) {
      const matches = words.every(word => normalize(card.dataset.search).includes(word));
      card.hidden = !(matches && (!group.value || card.dataset.group === group.value));
      if (!card.hidden) count++;
    }
    document.getElementById("tool-count").textContent = count ?
      `${count} de ${cards.length} ferramentas` : "Nenhuma ferramenta encontrada. Tente outro termo ou categoria.";
  };
  search.addEventListener("input", filterTools);
  group.addEventListener("change", filterTools);

  const first = tool => recordings.find(row => row.tool === tool && row.group !== "Preparar IDs");
  const scenarios = [
    {name: "A · Conhecer o projeto", rows: ["get_project_summary", "get_file_tree", "search_symbols", "get_symbol_source"].map(first)},
    {name: "B · Investigar uma mensagem de erro", rows: ["grep_content", "get_file_outline", "get_context_bundle"].map(first)},
    {name: "C · Avaliar impacto de uma mudança", rows: ["find_importers", "get_blast_radius", "get_dependency_graph", "get_call_hierarchy"].map(first)},
    {name: "D · Arquitetura e herança", rows: [first("get_dependency_cycles"), recordings.find(row => row.tool === "search_symbols" && row.args.query === "Order"), first("get_class_hierarchy")]},
    {name: "E · Atualização incremental", rows: recordings.filter(row => row.group === "Atualização incremental")},
    {name: "Extra · Paginação, cursor e erro parcial", rows: recordings.filter(row => row.group === "Paginação e limites")},
    {name: `Todas as ${recordings.length} chamadas`, rows: recordings}
  ];
  const selector = document.getElementById("demo-scenario");
  for (const [index, scenario] of scenarios.entries()) {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = scenario.name;
    selector.append(option);
  }
  let step = 0;
  let timer = null;
  const prev = document.getElementById("demo-prev");
  const next = document.getElementById("demo-next");
  const play = document.getElementById("demo-play");
  const rows = () => scenarios[Number(selector.value)].rows;
  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
    play.textContent = "Reproduzir";
    play.setAttribute("aria-pressed", "false");
  }
  function render() {
    const current = rows()[step];
    document.getElementById("demo-tool").textContent = current.tool;
    document.getElementById("demo-label").textContent = current.label;
    document.getElementById("demo-args").textContent = JSON.stringify(current.args, null, 2);
    document.getElementById("demo-result").textContent = JSON.stringify(current.result, null, 2);
    document.getElementById("demo-note").textContent = catalog.get(current.tool).note;
    document.getElementById("demo-progress").textContent = `${step + 1} / ${rows().length}`;
    document.querySelector(".demo-output").scrollTop = 0;
    prev.disabled = step === 0;
    next.disabled = step === rows().length - 1;
  }
  selector.addEventListener("change", () => { stop(); step = 0; render(); });
  prev.addEventListener("click", () => { stop(); if (step > 0) step--; render(); });
  next.addEventListener("click", () => { stop(); if (step < rows().length - 1) step++; render(); });
  play.addEventListener("click", () => {
    if (timer !== null) { stop(); return; }
    if (step === rows().length - 1) { step = 0; render(); }
    play.textContent = "Pausar";
    play.setAttribute("aria-pressed", "true");
    timer = setInterval(() => {
      if (step < rows().length - 1) { step++; render(); }
      if (step === rows().length - 1) stop();
    }, 4500);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  document.getElementById("recording-meta").textContent =
    `v${payload.recording.version} · stdio · ${payload.recording.call_count} chamadas`;
  document.querySelectorAll(".record-link").forEach(button => {
    button.addEventListener("click", () => {
      stop(); selector.value = String(scenarios.length - 1);
      step = recordings.indexOf(first(button.dataset.tool));
      render(); document.getElementById("demo-player").scrollIntoView();
      selector.focus({preventScroll: true});
    });
  });
  document.querySelectorAll("pre").forEach(pre => {
    const target = pre.querySelector("code");
    if (!target) return;
    const button = document.createElement("button");
    button.className = "copy-code";
    button.textContent = "Copiar";
    button.setAttribute("aria-label", "Copiar código deste bloco");
    button.addEventListener("click", async () => {
      try {
        if (!navigator.clipboard) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(target.textContent);
        button.textContent = "Copiado";
      } catch (_) {
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges(); selection.addRange(range);
        button.textContent = "Selecionado: Ctrl/Cmd+C";
      }
      setTimeout(() => { button.textContent = "Copiar"; }, 2500);
    });
    pre.append(button);
  });
  function openAnchor() {
    const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (target && target.classList.contains("tool-card")) {
      search.value = ""; group.value = ""; filterTools(); target.open = true;
    }
  }
  window.addEventListener("hashchange", openAnchor);
  const detailsState = new Map();
  window.addEventListener("beforeprint", () => {
    stop();
    cards.forEach(card => { detailsState.set(card, [card.open, card.hidden]); card.open = true; card.hidden = false; });
  });
  window.addEventListener("afterprint", () => {
    detailsState.forEach(([open, hidden], card) => { card.open = open; card.hidden = hidden; });
    detailsState.clear();
  });
  document.getElementById("print-manual").addEventListener("click", () => window.print());
  const navLinks = [...document.querySelectorAll("nav a")];
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        navLinks.forEach(link => link.classList.toggle("active", link.hash === `#${entry.target.id}`));
      }
    }, {rootMargin: "-5% 0px -70% 0px"});
    document.querySelectorAll("article>h2").forEach(heading => observer.observe(heading));
  }
  filterTools(); render(); openAnchor();
})();
