/**
 * src/mf_faq/ui/static/main.js
 * Frontend logic for the Phase 4 UI with Chat Sessions.
 */

class ChatManager {
    constructor() {
        this.sessions = JSON.parse(localStorage.getItem('chat_sessions')) || [];
        this.currentSessionId = null;
    }

    save() {
        localStorage.setItem('chat_sessions', JSON.stringify(this.sessions));
    }

    createNewSession() {
        const id = Date.now().toString();
        const session = {
            id: id,
            title: "New Chat",
            messages: []
        };
        this.sessions.unshift(session);
        this.currentSessionId = id;
        this.save();
        return id;
    }

    getSession(id) {
        return this.sessions.find(s => s.id === id);
    }

    getCurrentSession() {
        if (!this.currentSessionId && this.sessions.length > 0) {
            this.currentSessionId = this.sessions[0].id;
        } else if (!this.currentSessionId) {
            this.createNewSession();
        }
        return this.getSession(this.currentSessionId);
    }

    addMessage(role, content, meta = null) {
        const session = this.getCurrentSession();
        if (session.messages.length === 0 && role === 'user') {
            // Set title to first question
            session.title = content.length > 30 ? content.substring(0, 30) + '...' : content;
        }
        session.messages.push({ role, content, meta });
        this.save();
    }

    getHistoryForAPI(limit = 5) {
        const session = this.getCurrentSession();
        // Return last N messages, excluding the one we are about to add (handled by UI)
        // Convert to role/content dicts
        const apiHistory = session.messages.map(m => ({
            role: m.role === 'ai' ? 'assistant' : 'user',
            content: m.content
        }));
        return apiHistory.slice(-limit);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const chatManager = new ChatManager();
    
    // DOM Elements
    const form = document.getElementById('ask-form');
    const input = document.getElementById('question-input');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = document.querySelector('.btn-text');
    const spinner = document.getElementById('loading-spinner');
    
    const chatMessages = document.getElementById('chat-messages');
    const heroSection = document.getElementById('hero-section');
    const sessionList = document.getElementById('chat-sessions-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    
    const disclaimerText = document.getElementById('disclaimer-text');
    const metaUpdated = document.getElementById('meta-updated');
    const metaCount = document.getElementById('meta-schemes-count');
    const examplesContainer = document.getElementById('example-questions');
    
    // Mobile Sidebar Elements
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const menuToggle = document.getElementById('menu-toggle');
    const closeSidebarBtn = document.getElementById('close-sidebar-btn');

    function closeSidebar() {
        sidebar.classList.remove('open');
        sidebarOverlay.classList.remove('open');
    }

    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.add('open');
            sidebarOverlay.classList.add('open');
        });
    }
    
    if (closeSidebarBtn) {
        closeSidebarBtn.addEventListener('click', closeSidebar);
    }
    
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeSidebar);
    }

    const API_BASE = window.location.origin;

    const exampleQuestions = [
        "What is the expense ratio of HDFC Equity Fund?",
        "What is the exit load of HDFC Mid Cap Fund?",
        "What is the lock-in period for HDFC ELSS Tax Saver?"
    ];

    init();

    async function init() {
        // Populate examples
        exampleQuestions.forEach(q => {
            const btn = document.createElement('button');
            btn.className = 'example-btn';
            btn.textContent = q;
            btn.addEventListener('click', () => {
                input.value = q;
                input.focus();
            });
            examplesContainer.appendChild(btn);
        });

        // Fetch Metadata
        try {
            const res = await fetch(`${API_BASE}/meta`);
            if (res.ok) {
                const data = await res.json();
                disclaimerText.textContent = data.disclaimer;
                metaUpdated.textContent = data.last_updated;
                metaCount.textContent = data.schemes.length;
                
                // Populate Tracked Funds
                const fundList = document.getElementById('fund-list');
                if (fundList && data.schemes) {
                    data.schemes.forEach(scheme => {
                        const li = document.createElement('li');
                        li.textContent = scheme.name.split('—')[0].trim(); // Display shorter name
                        fundList.appendChild(li);
                    });
                }
            }
        } catch (e) {
            console.error("Meta fetch error:", e);
        }

        renderSidebar();
        loadCurrentSession();
    }

    newChatBtn.addEventListener('click', () => {
        chatManager.createNewSession();
        renderSidebar();
        loadCurrentSession();
        input.focus();
    });

    function renderSidebar() {
        sessionList.innerHTML = '';
        chatManager.sessions.forEach(session => {
            const div = document.createElement('div');
            div.className = `session-item ${session.id === chatManager.currentSessionId ? 'active' : ''}`;
            div.textContent = session.title;
            div.addEventListener('click', () => {
                chatManager.currentSessionId = session.id;
                renderSidebar();
                loadCurrentSession();
                if (typeof closeSidebar === 'function') closeSidebar();
            });
            sessionList.appendChild(div);
        });
    }

    function loadCurrentSession() {
        chatMessages.innerHTML = '';
        const session = chatManager.getCurrentSession();
        
        if (session.messages.length === 0) {
            heroSection.style.display = 'block';
            chatMessages.classList.add('hidden');
        } else {
            heroSection.style.display = 'none';
            chatMessages.classList.remove('hidden');
            session.messages.forEach(msg => {
                if (msg.role === 'user') {
                    appendUserBubble(msg.content);
                } else {
                    appendAIBubble(msg.content, msg.meta);
                }
            });
            scrollToBottom();
        }
    }

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Handle Form Submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const question = input.value.trim();
        if (!question) return;

        input.value = '';
        
        if (chatManager.getCurrentSession().messages.length === 0) {
            heroSection.style.display = 'none';
            chatMessages.classList.remove('hidden');
        }

        // Get history before adding new question
        const history = chatManager.getHistoryForAPI(5);
        
        // Add User Message
        chatManager.addMessage('user', question);
        appendUserBubble(question);
        scrollToBottom();
        renderSidebar(); // Update title if first message

        setLoading(true);

        try {
            const res = await fetch(`${API_BASE}/ask`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, history })
            });

            if (!res.ok) {
                throw new Error(`Server returned ${res.status}`);
            }

            const data = await res.json();
            
            const meta = data.source_url ? {
                route: data.route,
                source_url: data.source_url,
                footer: data.footer
            } : null;

            chatManager.addMessage('ai', data.answer, meta);
            appendAIBubble(data.answer, meta, true);
            scrollToBottom();
            
        } catch (error) {
            console.error("Ask error:", error);
            const errMeta = { route: 'refusal' };
            const errMsg = "An error occurred while connecting to the assistant. Please try again later.";
            chatManager.addMessage('ai', errMsg, errMeta);
            appendAIBubble(errMsg, errMeta, true);
            scrollToBottom();
        } finally {
            setLoading(false);
        }
    });

    function setLoading(isLoading) {
        if (isLoading) {
            submitBtn.disabled = true;
            btnText.classList.add('hidden');
            spinner.classList.remove('hidden');
        } else {
            submitBtn.disabled = false;
            btnText.classList.remove('hidden');
            spinner.classList.add('hidden');
        }
    }

    function appendUserBubble(text) {
        const div = document.createElement('div');
        div.className = 'message-bubble user';
        div.textContent = text;
        chatMessages.appendChild(div);
    }

    function appendAIBubble(text, meta, isNew = false) {
        const wrapper = document.createElement('div');
        wrapper.className = 'message-bubble ai answer-box';
        const timestamp = Date.now();
        
        let headerHtml = '';
        if (meta && meta.route) {
            const routeName = meta.route.replace('_', ' ');
            headerHtml = `
                <div class="answer-header">
                    <span class="ai-badge">AI Assistant</span>
                    <span class="route-badge route-${meta.route}">${routeName}</span>
                </div>
            `;
        }

        let metaHtml = '';
        if (meta && meta.source_url) {
            const footerText = meta.footer ? meta.footer.replace("Last updated from sources:", "").trim() : "Unknown date";
            metaHtml = `
                <div class="response-meta ${isNew ? 'hidden' : ''}" id="meta-${timestamp}">
                    <a href="${meta.source_url}" target="_blank" rel="noopener noreferrer" class="source-link">
                        <span class="link-icon">📎</span> <span>${meta.source_url}</span>
                    </a>
                    <p class="footer-text">🕒 ${footerText}</p>
                </div>
            `;
        }

        const pId = `resp-text-${timestamp}`;
        wrapper.innerHTML = `
            ${headerHtml}
            <p id="${pId}" class="response-text" style="margin-bottom: ${metaHtml ? '1.5rem' : '0'}">${isNew ? '' : text}</p>
            ${metaHtml}
        `;
        
        chatMessages.appendChild(wrapper);

        if (isNew) {
            // Typing effect
            const p = document.getElementById(pId);
            const metaContainer = document.getElementById(`meta-${timestamp}`);
            let i = 0;
            const speed = 10; // ms per char
            
            function typeWriter() {
                if (i < text.length) {
                    p.textContent += text.charAt(i);
                    i++;
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                    setTimeout(typeWriter, speed);
                } else {
                    if (metaContainer) {
                        metaContainer.classList.remove('hidden');
                        metaContainer.classList.add('fade-in-up');
                    }
                }
            }
            typeWriter();
        }
    }
});
