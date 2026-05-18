const feedEl = document.getElementById("feed");
const userIdEl = document.getElementById("userId");
const postToLoadEl = document.getElementById("postToLoad");
const loadFeedButton = document.getElementById("loadFeedButton");
const loadMoreButton = document.getElementById("loadMoreButton");
const resetButton = document.getElementById("resetButton");
const loadedCountEl = document.getElementById("loadedCount");
const errorBox = document.getElementById("errorBox");
const endMessage = document.getElementById("endMessage");

let loadedPostIds = new Set();
let isLoading = false;

function formatDate(value) {
	if (!value) return "data non disponibile";
	return new Intl.DateTimeFormat("it-IT", {
		dateStyle: "medium",
		timeStyle: "short"
	}).format(new Date(value));
}

function formatAge(hours) {
	if (hours < 1) return "meno di 1 ora fa";
	if (hours < 24) return `${Math.round(hours)} ore fa`;
	return `${Math.round(hours / 24)} giorni fa`;
}

function setLoading(value) {
	isLoading = value;
	loadFeedButton.disabled = value;
	loadMoreButton.disabled = value;
	loadFeedButton.textContent = value ? "Caricamento..." : "Carica feed";
	loadMoreButton.textContent = value ? "Caricamento..." : "Carica altri 20 post";
}

function showError(message) {
	errorBox.textContent = message;
	errorBox.classList.remove("hidden");
}

function clearError() {
	errorBox.textContent = "";
	errorBox.classList.add("hidden");
}

function createPostCard(post, absoluteIndex) {
	const article = document.createElement("article");
	article.className = "card";

	const followedBadge = post.from_followed_user
		? `<span class="badge followed">autore seguito</span>`
		: `<span class="badge">autore non seguito</span>`;

	article.innerHTML = `
    <div class="card-header">
      <div>
        <h2 class="card-title">#${absoluteIndex} - Post ${post.post_id}</h2>
        <div class="card-meta">
          Autore user_id=${post.user_id} · ${formatDate(post.created_at)} · ${formatAge(post.age_hours)}
        </div>
      </div>
      <div class="score">score ${post.score.toFixed(3)}</div>
    </div>

    <p class="content"></p>

    <div class="badges">
      ${followedBadge}
      <span class="badge">likes ${post.like_count}</span>
      <span class="badge">affinity ${post.affinity_score}</span>
    </div>
  `;

	article.querySelector(".content").textContent = post.content;
	return article;
}

async function loadPosts({ reset = false } = {}) {
	if (isLoading) return;

	clearError();
	endMessage.classList.add("hidden");

	if (reset) {
		loadedPostIds = new Set();
		feedEl.innerHTML = "";
		loadedCountEl.textContent = "0";
		loadMoreButton.classList.add("hidden");
	}

	const userId = userIdEl.value.trim();
	if (!userId) {
		showError("Inserisci uno user_id valido.");
		return;
	}

	const postToLoad = postToLoadEl.value.trim();
	if (!userId) {
		showError("Inserisci un numero di post valido.");
		return;
	}

	const params = new URLSearchParams({
		user_id: userId,
		limit: postToLoad,
		loaded_ids: Array.from(loadedPostIds).join(",")
	});

	setLoading(true);

	try {
		const response = await fetch(`/api/fyp?${params.toString()}`);
		const data = await response.json();

		if (!response.ok) {
			throw new Error(data.error || "Errore durante il caricamento dei post.");
		}

		const newPosts = data.posts.filter(post => !loadedPostIds.has(post.post_id));

		newPosts.forEach(post => {
			loadedPostIds.add(post.post_id);
			const card = createPostCard(post, loadedPostIds.size);
			feedEl.appendChild(card);
		});

		loadedCountEl.textContent = String(loadedPostIds.size);

		if (newPosts.length === postToLoad) {
			loadMoreButton.classList.remove("hidden");
		} else {
			loadMoreButton.classList.add("hidden");
			endMessage.classList.remove("hidden");
		}
	} catch (error) {
		showError(error.message);
	} finally {
		setLoading(false);
	}
}

loadFeedButton.addEventListener("click", () => loadPosts({ reset: true }));
loadMoreButton.addEventListener("click", () => loadPosts({ reset: false }));
resetButton.addEventListener("click", () => {
	loadedPostIds = new Set();
	feedEl.innerHTML = "";
	loadedCountEl.textContent = "0";
	loadMoreButton.classList.add("hidden");
	endMessage.classList.add("hidden");
	clearError();
});

loadPosts({ reset: true });
