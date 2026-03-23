"""Script to update widget with URL params, share button, and AJAX cart."""

with open('shopify_widget.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add CSS for share button
old_toast_css = '.beer-rec-toast { position: fixed;'
new_toast_css = '''.beer-rec-share-btn { background: #667eea; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; margin-left: 15px; transition: background 0.2s; }
  .beer-rec-share-btn:hover { background: #5a6fd6; }
  .beer-rec-share-btn svg { width: 16px; height: 16px; }
  .beer-rec-toast { position: fixed;'''

content = content.replace(old_toast_css, new_toast_css)

# 2. Update JS to handle URL params and add share functionality
old_init = '''var beerRec = (function() {
  var API_BASE = "https://recommendation.houseofbeers.nl/api";
  var currentUsername = "";

  // Load styles on page load
  loadStyles();'''

new_init = '''var beerRec = (function() {
  var API_BASE = "https://recommendation.houseofbeers.nl/api";
  var currentUsername = "";
  var lastRecData = null;
  var lastProfileData = null;

  // Check URL params on page load
  initFromUrl();
  loadStyles();

  function initFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var username = params.get("untappd");
    if (username) {
      document.getElementById("untappdUsername").value = username;
      // Auto-load recommendations after a short delay
      setTimeout(function() { getRecommendations(); }, 500);
    }
  }

  function updateUrl(username) {
    var url = new URL(window.location.href);
    url.searchParams.set("untappd", username);
    window.history.replaceState({}, "", url);
  }

  function getShareUrl() {
    var url = new URL(window.location.href);
    url.searchParams.set("untappd", currentUsername);
    return url.toString();
  }

  function copyShareLink() {
    var shareUrl = getShareUrl();
    navigator.clipboard.writeText(shareUrl).then(function() {
      showToast("Link copied to clipboard!");
    }).catch(function() {
      // Fallback for older browsers
      prompt("Copy this link:", shareUrl);
    });
  }'''

content = content.replace(old_init, new_init)

# 3. Update getRecommendations to update URL
old_get_recs = '''    currentUsername = username;
    showLoading(true, "Submitting request...");'''

new_get_recs = '''    currentUsername = username;
    updateUrl(username);
    showLoading(true, "Submitting request...");'''

content = content.replace(old_get_recs, new_get_recs)

# 4. Update fetchProfileAndDisplay to store data
old_fetch_display = '''  function fetchProfileAndDisplay(recData) {
    // Fetch detailed profile for radar chart
    fetch(API_BASE + "/profile/" + currentUsername + "/")
      .then(function(r) { return r.json(); })
      .then(function(profileData) {
        displayResults(recData, profileData);
        showLoading(false);
      })
      .catch(function(e) {
        // Fall back to displaying without detailed profile
        displayResults(recData, null);
        showLoading(false);
      });
  }'''

new_fetch_display = '''  function fetchProfileAndDisplay(recData) {
    // Store recData for potential re-display
    lastRecData = recData;
    // Fetch detailed profile for radar chart
    fetch(API_BASE + "/profile/" + currentUsername + "/")
      .then(function(r) { return r.json(); })
      .then(function(profileData) {
        lastProfileData = profileData;
        displayResults(recData, profileData);
        showLoading(false);
      })
      .catch(function(e) {
        // Fall back to displaying without detailed profile
        displayResults(recData, null);
        showLoading(false);
      });
  }'''

content = content.replace(old_fetch_display, new_fetch_display)

# 5. Find the profile section in displayResults and add share button
# Look for where profile header is rendered
old_profile_header = '''html += \'<div class="beer-rec-profile"><h3>\' + profile.username + "\'s Taste Profile</h3>";'''
new_profile_header = '''html += '<div class="beer-rec-profile"><h3>' + profile.username + "'s Taste Profile";
    html += '<button class="beer-rec-share-btn" onclick="beerRec.copyShareLink()" title="Copy shareable link">';
    html += '<svg fill="currentColor" viewBox="0 0 20 20"><path d="M15 8a3 3 0 10-2.977-2.63l-4.94 2.47a3 3 0 100 4.319l4.94 2.47a3 3 0 10.895-1.789l-4.94-2.47a3.027 3.027 0 000-.74l4.94-2.47C13.456 7.68 14.19 8 15 8z"></path></svg>';
    html += 'Share</button></h3>';'''

content = content.replace(old_profile_header, new_profile_header)

# 6. Update addToCart to NOT reload page - use event.preventDefault
old_addtocart = '''  function addToCart(variantId, btn) {
    if (!variantId) return;
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Adding...";
    fetch("/cart/add.js", {'''

new_addtocart = '''  function addToCart(variantId, btn, event) {
    if (event) event.preventDefault();
    if (!variantId) return;
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Adding...";
    fetch("/cart/add.js", {'''

content = content.replace(old_addtocart, new_addtocart)

# 7. Update button onclick to pass event
old_btn_onclick = '''onclick="beerRec.addToCart(\\'\\' + variantId + \\'\\', this)"'''
new_btn_onclick = '''onclick="beerRec.addToCart('\\' + variantId + \\'' , this, event)"'''

# This pattern might be different, let's try more carefully
old_btn = '''<button class="beer-rec-add-btn" onclick="beerRec.addToCart(\\'\' + variantId + \\'\\', this)">Add to Cart</button>'''
new_btn = '''<button class="beer-rec-add-btn" onclick="beerRec.addToCart('\\' + variantId + '\\', this, event)">Add to Cart</button>'''

# Try multiple patterns
if old_btn in content:
    content = content.replace(old_btn, new_btn)
else:
    # Try simpler replacement
    content = content.replace(
        "onclick=\"beerRec.addToCart('\" + variantId + \"', this)\"",
        "onclick=\"beerRec.addToCart('\" + variantId + \"', this, event)\""
    )

# 8. Add copyShareLink to the exports
old_exports = '''    addToCart: addToCart
  };
})();'''

new_exports = '''    addToCart: addToCart,
    copyShareLink: copyShareLink
  };
})();'''

content = content.replace(old_exports, new_exports)

with open('shopify_widget.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('Widget updated with URL params, share button, and AJAX cart!')
