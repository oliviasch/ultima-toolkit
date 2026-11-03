const SUMMARY_LIMIT = 4;

function tagChip(tag, removable) {
  if (!removable) {
    const chip = document.createElement("span");
    chip.className = "tag";
    chip.textContent = tag;
    return chip;
  }
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "tag";
  chip.dataset.remove = tag;
  chip.title = `Remove ${tag}`;
  chip.append(tag);
  const cross = document.createElement("span");
  cross.className = "x";
  cross.textContent = "\u00d7";
  chip.append(cross);
  return chip;
}

function paint(box, tags) {
  const removable = box.classList.contains("tag-list");
  if (removable) {
    box.replaceChildren(...tags.map(tag => tagChip(tag, true)));
    return;
  }
  box.replaceChildren(...tags.slice(0, SUMMARY_LIMIT).map(tag => tagChip(tag, false)));
  if (tags.length > SUMMARY_LIMIT) {
    const more = document.createElement("span");
    more.className = "tag more";
    more.textContent = `+${tags.length - SUMMARY_LIMIT}`;
    box.append(more);
  }
  box.hidden = tags.length === 0;
}

function matchesFilter(tags) {
  const input = document.querySelector(".tag-filter-input");
  const query = input ? input.value.trim().toLowerCase() : "";
  return !query || tags.some(tag => tag.toLowerCase().includes(query));
}

async function save(panel, action, tag) {
  if (panel.dataset.busy === "1") return null;
  panel.dataset.busy = "1";
  const body = new URLSearchParams({
    steamid: panel.dataset.steamid,
    appid: panel.dataset.appid,
    sort: panel.dataset.sort || "",
    action,
    tag: tag || "",
  });

  try {
    const response = await fetch("/tags", {
      method: "POST",
      headers: { Accept: "application/json" },
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Could not save tags.");
    const saved = data.tags || [];
    for (const box of document.querySelectorAll(`[data-tags-for="${panel.dataset.appid}"]`)) {
      paint(box, saved);
      const game = box.closest(".game");
      if (game) game.hidden = !matchesFilter(saved);
    }
    return saved;
  } catch (error) {
    panel.classList.add("tag-error");
    setTimeout(() => panel.classList.remove("tag-error"), 1200);
    return null;
  } finally {
    delete panel.dataset.busy;
  }
}

document.addEventListener("click", event => {
  const chip = event.target.closest(".tag-list [data-remove]");
  if (!chip) return;
  event.preventDefault();
  const panel = chip.closest(".tag-panel");
  if (panel) save(panel, "remove", chip.dataset.remove);
});

document.addEventListener("submit", event => {
  const form = event.target.closest(".tag-add");
  if (!form) return;
  event.preventDefault();
  const panel = form.closest(".tag-panel");
  const input = form.querySelector(".tag-input");
  const value = input.value.trim();
  if (!panel || !value) return;
  save(panel, "add", value).then(tags => {
    if (tags) input.value = "";
  });
});
