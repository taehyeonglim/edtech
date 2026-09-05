// Include self-check explanations in print, then restore the reader's choices.
(() => {
  let printState = null;

  window.addEventListener("beforeprint", () => {
    if (printState) return;
    printState = new Map();
    document.querySelectorAll(".md-typeset details.question").forEach((answer) => {
      printState.set(answer, answer.open);
      answer.open = true;
    });
  });

  window.addEventListener("afterprint", () => {
    if (!printState) return;
    printState.forEach((wasOpen, answer) => { answer.open = wasOpen; });
    printState = null;
  });
})();
