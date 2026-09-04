(function () {
  "use strict";

  function selectedOption(select) {
    return select.options[select.selectedIndex] || select.options[0] || null;
  }

  function enhanceSelect(select) {
    if (!(select instanceof HTMLSelectElement) || select.dataset.studioEnhanced === "true") return;
    if (!select.classList.contains("form-select") || select.dataset.nativeSelect === "true") return;

    const shell = document.createElement("div");
    shell.className = "studio-select-shell dropdown";
    select.parentNode.insertBefore(shell, select);
    shell.append(select);
    select.dataset.studioEnhanced = "true";
    select.classList.add("studio-native-select");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    const button = document.createElement("button");
    button.type = "button";
    button.className = "studio-select-button";
    button.dataset.bsToggle = "dropdown";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", select.getAttribute("aria-label") || "선택 메뉴");
    const label = document.createElement("span");
    label.className = "text-truncate";
    const chevron = document.createElement("i");
    chevron.className = "bi bi-chevron-down studio-select-chevron";
    button.append(label, chevron);

    const menu = document.createElement("div");
    menu.className = "dropdown-menu studio-select-menu";
    shell.append(button, menu);

    function sync() {
      const option = selectedOption(select);
      label.textContent = option ? option.textContent.trim() : "선택";
      button.disabled = select.disabled;
      button.setAttribute("aria-label", select.getAttribute("aria-label") || label.textContent);
      menu.querySelectorAll("[data-studio-option]").forEach(function (item) {
        const active = item.dataset.studioOption === select.value;
        item.classList.toggle("is-selected", active);
        item.setAttribute("aria-selected", String(active));
      });
    }

    function rebuild() {
      menu.replaceChildren();
      Array.from(select.options).forEach(function (option) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "studio-select-option";
        item.dataset.studioOption = option.value;
        item.disabled = option.disabled;
        item.setAttribute("role", "option");
        const copy = document.createElement("span");
        copy.className = "text-truncate";
        copy.textContent = option.textContent.trim();
        const check = document.createElement("i");
        check.className = "bi bi-check-lg";
        item.append(copy, check);
        item.addEventListener("click", function () {
          if (option.disabled) return;
          select.value = option.value;
          select.dispatchEvent(new Event("change", {bubbles: true}));
          sync();
          window.bootstrap.Dropdown.getOrCreateInstance(button).hide();
        });
        menu.append(item);
      });
      sync();
    }

    select.addEventListener("change", sync);
    new MutationObserver(rebuild).observe(select, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["disabled", "selected", "label"]
    });
    select._studioSelectSync = sync;
    rebuild();
  }

  function scan(root) {
    if (root instanceof HTMLSelectElement) enhanceSelect(root);
    if (root.querySelectorAll) root.querySelectorAll("select.form-select").forEach(enhanceSelect);
  }

  window.StudioControls = {
    enhanceSelect: enhanceSelect,
    syncSelect: function (select) {
      if (select && typeof select._studioSelectSync === "function") select._studioSelectSync();
    }
  };

  scan(document);
  new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(function (node) {
        if (node.nodeType === Node.ELEMENT_NODE) scan(node);
      });
    });
  }).observe(document.body, {childList: true, subtree: true});
})();
