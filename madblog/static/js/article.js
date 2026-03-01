(function () {
  function getArticle() {
    var articles = document.getElementsByTagName("article");
    if (!articles.length) {
      return;
    }

    return articles[0];
  }

  function addCopyButton(article) {
    var codeBlocks = article.querySelectorAll(".codehilite");
    codeBlocks.forEach(function (codeBlock) {
      var pre = codeBlock.querySelector("pre");
      var code = pre.querySelector("code");
      var copyButton = document.createElement("button");
      copyButton.classList.add("copy-button");
      copyButton.type = "button";
      copyButton.title = "Copy to clipboard";
      copyButton.innerHTML = "&#128203;";
      copyButton.addEventListener("click", function () {
        navigator.clipboard.writeText(code.textContent.trim());
      });
      pre.appendChild(copyButton);
    });
  }

  var article = getArticle();
  if (!article) {
    return;
  }

  addCopyButton(article);
})();
