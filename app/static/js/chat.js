// Public chat page behaviour: scrolling, starter questions, errors and
// catching up after the live connection dropped (phones in the background).
(function () {
    const history = document.getElementById('chat-history');
    const container = document.getElementById('messages-container');
    const form = document.getElementById('chat-input-form');
    const input = document.getElementById('chat-input');
    const scrollBtn = document.getElementById('scroll-to-bottom-btn');
    if (!history || !container || !form || !input) return;

    const NEAR_BOTTOM_PX = 80;
    let stickToBottom = true;

    function isNearBottom() {
        return history.scrollHeight - history.scrollTop - history.clientHeight < NEAR_BOTTOM_PX;
    }

    function scrollToBottom(smooth) {
        history.scrollTo({ top: history.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
        if (scrollBtn) scrollBtn.classList.remove('visible');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // A short notice in the conversation, for errors the server could not send itself.
    function showChatNotice(text) {
        container.insertAdjacentHTML(
            'beforeend',
            '<div class="message system-message error slide-in" role="alert">' + escapeHtml(text) + '</div>'
        );
        scrollToBottom(true);
    }
    window.showChatNotice = showChatNotice;

    function removeStarters() {
        const starters = document.getElementById('starter-questions');
        if (starters) starters.remove();
    }

    // Start at the latest message.
    scrollToBottom(false);

    history.addEventListener('scroll', function () {
        stickToBottom = isNearBottom();
        if (stickToBottom && scrollBtn) scrollBtn.classList.remove('visible');
    }, { passive: true });

    if (scrollBtn) {
        scrollBtn.addEventListener('click', function () { scrollToBottom(true); });
    }

    // New messages: follow them if the reader is at the bottom (or just sent
    // one); otherwise leave the reader where they are and offer the button.
    history.addEventListener('htmx:sseBeforeMessage', function () {
        stickToBottom = isNearBottom();
    });
    history.addEventListener('htmx:sseMessage', function (evt) {
        const data = (evt.detail && evt.detail.data) || '';
        const ownMessage = data.indexOf('message user') !== -1;
        if (ownMessage) removeStarters();
        if (stickToBottom || ownMessage) {
            scrollToBottom(true);
        } else if (scrollBtn) {
            scrollBtn.classList.add('visible');
        }
    });

    // Starter questions send themselves.
    document.querySelectorAll('.starter-chip').forEach(function (chip) {
        chip.addEventListener('click', function () {
            input.value = chip.dataset.question || chip.textContent.trim();
            removeStarters();
            form.requestSubmit();
        });
    });

    // Errors on sending: show what the server said and keep the typed text.
    form.addEventListener('htmx:responseError', function (evt) {
        const xhr = evt.detail.xhr;
        const body = xhr && xhr.responseText ? xhr.responseText.trim() : '';
        if (body && body.indexOf('<div') === 0) {
            container.insertAdjacentHTML('beforeend', body);
            scrollToBottom(true);
        } else if (xhr && xhr.status === 429) {
            showChatNotice("You're sending messages a bit too fast. Please wait a moment and try again.");
        } else {
            showChatNotice('Your message could not be sent. Please try again.');
        }
    });
    form.addEventListener('htmx:sendError', function () {
        showChatNotice('No connection to the server. Check your internet connection and try again.');
    });

    // Catch up after the live connection dropped: messages sent while it was
    // down (for example while the phone was locked) are loaded from the page.
    let lostConnection = false;
    let hiddenSince = null;
    let syncing = false;

    function resync() {
        if (syncing) return;
        syncing = true;
        fetch(window.location.pathname, { credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
            .then(function (res) { return res.ok ? res.text() : Promise.reject(res.status); })
            .then(function (html) {
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const fresh = doc.getElementById('messages-container');
                if (!fresh) return;
                const typing = document.getElementById('typing-indicator');
                const wasNearBottom = isNearBottom();
                container.innerHTML = fresh.innerHTML;
                // An answer that is still being written keeps its typing bubble.
                if (typing && !fresh.querySelector('#typing-indicator')) {
                    const msgs = container.querySelectorAll('.message');
                    const last = msgs[msgs.length - 1];
                    if (last && last.classList.contains('user')) container.appendChild(typing);
                }
                htmx.process(container);
                if (wasNearBottom) scrollToBottom(false);
            })
            .catch(function () { /* the next reconnect tries again */ })
            .finally(function () { syncing = false; });
    }

    history.addEventListener('htmx:sseError', function () { lostConnection = true; });
    history.addEventListener('htmx:sseOpen', function () {
        if (lostConnection) {
            lostConnection = false;
            resync();
        }
    });
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') {
            hiddenSince = Date.now();
        } else if (hiddenSince && Date.now() - hiddenSince > 5000) {
            hiddenSince = null;
            resync();
        }
    });

    // On phones the keyboard shrinks the view: keep the latest message in sight.
    input.addEventListener('focus', function () {
        if (stickToBottom) setTimeout(function () { scrollToBottom(false); }, 300);
    });
})();
