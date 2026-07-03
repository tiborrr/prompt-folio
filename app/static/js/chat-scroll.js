(function () {
    const BOTTOM_THRESHOLD_PX = 48;

    function isNearBottom(scroller) {
        return (
            scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <=
            BOTTOM_THRESHOLD_PX
        );
    }

    function scrollToBottom(scroller) {
        scroller.scrollTop = scroller.scrollHeight;
    }

    function scheduleScrollToBottom(scroller) {
        requestAnimationFrame(function () {
            scrollToBottom(scroller);
            requestAnimationFrame(function () {
                scrollToBottom(scroller);
            });
        });
    }

    function initChatScroller(scroller) {
        if (scroller.dataset.chatScrollInitialized === "true") {
            return;
        }
        scroller.dataset.chatScrollInitialized = "true";

        var messagesContainer = scroller.querySelector("#messages-container");
        if (!messagesContainer) {
            return;
        }

        var pinnedToBottom = true;
        var scrollToBottomBtn = scroller.parentElement ? scroller.parentElement.querySelector("#scroll-to-bottom-btn") : null;

        function updatePinnedState() {
            pinnedToBottom = isNearBottom(scroller);
            if (pinnedToBottom && scrollToBottomBtn) {
                scrollToBottomBtn.classList.remove("visible");
            }
        }

        scroller.addEventListener("scroll", updatePinnedState, { passive: true });

        var bottomIndicator = scroller.querySelector(".indicator-bottom");
        if (bottomIndicator) {
            var pinObserver = new IntersectionObserver(
                function (entries) {
                    entries.forEach(function (entry) {
                        if (entry.isIntersecting) {
                            pinnedToBottom = true;
                            if (scrollToBottomBtn) {
                                scrollToBottomBtn.classList.remove("visible");
                            }
                        }
                    });
                },
                { root: scroller, threshold: 0 }
            );
            pinObserver.observe(bottomIndicator);
        }

        function maybeScrollToBottom() {
            if (pinnedToBottom) {
                scheduleScrollToBottom(scroller);
                if (scrollToBottomBtn) {
                    scrollToBottomBtn.classList.remove("visible");
                }
            } else {
                if (scrollToBottomBtn) {
                    // Check if there's actually a message inside (not empty scroller)
                    var children = messagesContainer.children;
                    if (children.length > 1) {
                        scrollToBottomBtn.classList.add("visible");
                    }
                }
            }
        }

        var messageObserver = new MutationObserver(maybeScrollToBottom);
        messageObserver.observe(messagesContainer, {
            childList: true,
            subtree: true,
            characterData: true,
        });

        if (typeof ResizeObserver !== "undefined") {
            var resizeObserver = new ResizeObserver(maybeScrollToBottom);
            resizeObserver.observe(messagesContainer);
        }

        if (scrollToBottomBtn) {
            scrollToBottomBtn.addEventListener("click", function() {
                pinnedToBottom = true;
                scroller.scrollTo({
                    top: scroller.scrollHeight,
                    behavior: "smooth"
                });
                scrollToBottomBtn.classList.remove("visible");
            });
        }

        var panel = scroller.closest(".chat-panel, .glass-panel");
        if (panel) {
            panel.querySelectorAll("form").forEach(function (form) {
                form.addEventListener("submit", function () {
                    pinnedToBottom = true;
                    scheduleScrollToBottom(scroller);
                });
            });
        }

        scheduleScrollToBottom(scroller);
    }

    function initAllChatScrollers() {
        document.querySelectorAll("#chat-history").forEach(initChatScroller);
    }

    document.addEventListener("DOMContentLoaded", initAllChatScrollers);
    document.body.addEventListener("htmx:afterSwap", initAllChatScrollers);
})();
