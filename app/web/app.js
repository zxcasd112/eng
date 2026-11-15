// ENG TUTOR Web Client — Grey Zinc Minimalist Architecture

const API_BASE = '/api/v1';

// Study Queue Pure State Manager (Exportable for Unit Testing)
function createStudyQueueManager() {
  let queue = [];
  let index = 0;
  let isRevealed = false;
  let filter = 'ALL';
  let isSubmitting = false;

  return {
    getQueue: () => queue,
    getIndex: () => index,
    isAnswerRevealed: () => isRevealed,
    getFilter: () => filter,
    isSubmitting: () => isSubmitting,
    getCurrentCard: () => queue[index] || null,
    setFilter: (newFilter) => {
      filter = newFilter;
      index = 0;
      isRevealed = false;
      return filter;
    },
    setQueue: (newCards) => {
      queue = Array.isArray(newCards) ? newCards : [];
      index = 0;
      isRevealed = false;
      return queue;
    },
    revealAnswer: () => {
      isRevealed = true;
    },
    canSubmit: () => !isSubmitting && index < queue.length,
    startSubmit: () => {
      if (isSubmitting) return false;
      isSubmitting = true;
      return true;
    },
    finishSubmitSuccess: () => {
      isSubmitting = false;
      index++;
      isRevealed = false;
      return index;
    },
    finishSubmitFailure: () => {
      isSubmitting = false;
      // Network/server failure does NOT advance the queue!
      return index;
    },
    reset: () => {
      queue = [];
      index = 0;
      isRevealed = false;
      isSubmitting = false;
    }
  };
}

const studyQueueManager = createStudyQueueManager();

// Global App State
let currentUser = null;
let currentRoute = '/app';

// Study Session State (synced with studyQueueManager)
let studyQueue = [];
let studyIndex = 0;
let isAnswerRevealed = false;
let studyTypeFilter = 'ALL';

// Words Deck State
const wordsState = {
  items: [],
  page: 1,
  pageSize: 12,
  total: 0,
  query: '',
  cefr: 'ALL',
  status: 'ALL',
  searchTimer: null
};

// Quiz Lab State
let currentQuiz = null;
let isSubmittingQuiz = false;

// Toast Notification System
function showToast(message, type = 'info') {
  if (typeof document === 'undefined') return;
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.style.cssText = 'position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none;';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  const bg = type === 'error' ? 'var(--color-danger-bg)' : (type === 'success' ? 'var(--color-success-bg)' : 'var(--color-surface)');
  const border = type === 'error' ? 'var(--color-danger-border)' : (type === 'success' ? 'var(--color-success-border)' : 'var(--color-border)');
  const color = type === 'error' ? 'var(--color-danger)' : (type === 'success' ? 'var(--color-success)' : 'var(--color-text-primary)');

  toast.style.cssText = `pointer-events: auto; background: ${bg}; border: 1px solid ${border}; color: ${color}; padding: 12px 18px; border-radius: var(--radius-md); font-size: 0.875rem; box-shadow: var(--shadow-lg); transition: all 0.25s ease; opacity: 0; transform: translateY(10px); max-width: 380px;`;
  toast.textContent = message;
  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 250);
  }, 4000);
}

// Audio Pronunciation via Web Speech API
function speakWord(text) {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 0.92;
    window.speechSynthesis.speak(utterance);
  }
}

// Unified API Fetch with Cookie Authentication & Resilient Error Handling
async function fetchAPI(endpoint, options = {}) {
  const silent = options.silent || endpoint.startsWith('/auth/me') || endpoint.startsWith('/auth/widget-config');
  const defaultHeaders = {};
  if (!(options.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const opts = {
    ...options,
    credentials: 'include',
    headers: {
      ...defaultHeaders,
      ...(options.headers || {})
    }
  };

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, opts);
    if (res.status === 401) {
      currentUser = null;
      return { ok: false, status: 401, error: 'Unauthorized' };
    }

    const contentType = res.headers.get('content-type') || '';
    let data = null;
    if (contentType.includes('application/json')) {
      data = await res.json();
    } else {
      data = await res.text();
    }

    if (res.status >= 500 && !silent) {
      showToast('Ошибка сервера (5xx). Повторите попытку позже.', 'error');
    }

    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    if (!silent) {
      showToast('Сетевая ошибка: проверьте интернет-соединение.', 'error');
    }
    return { ok: false, status: 0, error: err.message, networkError: true };
  }
}

// Check Authentication Status
async function checkAuth() {
  try {
    const res = await fetchAPI('/auth/me');
    if (res.ok && res.data) {
      currentUser = res.data;
      updateUserUI();
      return currentUser;
    }
  } catch (err) {
    console.warn('Auth check error:', err);
  }
  currentUser = null;
  updateUserUI();
  return null;
}

function updateUserUI() {
  const badge = document.getElementById('userBadge');
  const streakBadge = document.getElementById('streakBadge');
  const logoutBtn = document.getElementById('logoutBtn');
  const navLinks = document.getElementById('appNavLinks');
  const mobileSubnav = document.getElementById('mobileSubnav');

  if (currentUser) {
    if (badge) {
      badge.style.display = 'inline-flex';
      if (currentUser.username) {
        badge.textContent = '@' + currentUser.username;
      } else if (currentUser.email) {
        badge.textContent = currentUser.email.split('@')[0];
      } else if (currentUser.telegram_id) {
        badge.textContent = 'TG: ' + currentUser.telegram_id;
      } else {
        badge.textContent = 'ID: ' + currentUser.id;
      }
    }
    if (logoutBtn) logoutBtn.style.display = 'inline-flex';
    if (navLinks) navLinks.style.display = 'flex';
    if (mobileSubnav && window.innerWidth <= 768) mobileSubnav.style.display = 'flex';
  } else {
    if (badge) badge.style.display = 'none';
    if (streakBadge) streakBadge.style.display = 'none';
    if (logoutBtn) logoutBtn.style.display = 'none';
    if (navLinks) navLinks.style.display = 'none';
    if (mobileSubnav) mobileSubnav.style.display = 'none';
  }
}

// SPA Router
function navigate(path) {
  if (path !== window.location.pathname) {
    window.history.pushState(null, '', path);
  }
  renderRoute();
}

if (typeof window !== 'undefined') {
  window.addEventListener('popstate', renderRoute);
}

async function renderRoute() {
  const path = window.location.pathname.replace(/\/$/, '') || '/app';
  currentRoute = path;

  // Views references
  const loadingView = document.getElementById('loadingView');
  const loginView = document.getElementById('loginView');
  const dashboardView = document.getElementById('dashboardView');
  const studyView = document.getElementById('studyView');
  const wordsView = document.getElementById('wordsView');
  const readingView = document.getElementById('readingView');
  const practiceView = document.getElementById('practiceView');
  const mistakesView = document.getElementById('mistakesView');
  const tutorView = document.getElementById('tutorView');
  const analyticsView = document.getElementById('analyticsView');
  const profileView = document.getElementById('profileView');

  // Hide all views first
  [loadingView, loginView, dashboardView, studyView, wordsView, readingView, practiceView, mistakesView, tutorView, analyticsView, profileView].forEach(v => {
    if (v) v.style.display = 'none';
  });

  // Ensure user is authenticated
  if (!currentUser) {
    const authUser = await checkAuth();
    if (!authUser) {
      if (loginView) {
        loginView.style.display = 'block';
        initTelegramLoginWidget();
      }
      updateNavActiveState('/app');
      return;
    }
  }

  // Update active states on nav buttons
  updateNavActiveState(path);

  // Check onboarding for first-time visitors
  checkAndShowOnboarding();

  // Render view
  if (path === '/app/study') {
    if (studyView) studyView.style.display = 'block';
    loadStudyQueue();
  } else if (path === '/app/words') {
    if (wordsView) wordsView.style.display = 'block';
    loadWordsDeck();
  } else if (path === '/app/reading') {
    if (readingView) readingView.style.display = 'block';
    loadReading();
  } else if (path === '/app/practice') {
    if (practiceView) practiceView.style.display = 'block';
    loadPractice();
  } else if (path === '/app/mistakes') {
    if (mistakesView) mistakesView.style.display = 'block';
    loadMistakes();
  } else if (path === '/app/tutor') {
    if (tutorView) tutorView.style.display = 'block';
    loadTutor();
  } else if (path === '/app/analytics') {
    if (analyticsView) analyticsView.style.display = 'block';
    loadAnalytics();
  } else if (path === '/app/profile') {
    if (profileView) profileView.style.display = 'block';
    loadProfile();
  } else {
    // Default to /app (Dashboard)
    if (dashboardView) dashboardView.style.display = 'block';
    loadDashboard();
  }
}

function updateNavActiveState(currentPath) {
  document.querySelectorAll('.app-nav-pill').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-route') === currentPath);
  });
}

// Auth Tab Switcher (Telegram vs Gmail)
function switchAuthTab(tab) {
  const secTg = document.getElementById('authSectionTelegram');
  const secGm = document.getElementById('authSectionGmail');
  const btnTg = document.getElementById('tabTelegramBtn');
  const btnGm = document.getElementById('tabGmailBtn');

  if (tab === 'gmail') {
    if (secTg) secTg.style.display = 'none';
    if (secGm) secGm.style.display = 'block';
    if (btnTg) btnTg.classList.remove('active');
    if (btnGm) btnGm.classList.add('active');
  } else {
    if (secTg) secTg.style.display = 'block';
    if (secGm) secGm.style.display = 'none';
    if (btnTg) btnTg.classList.add('active');
    if (btnGm) btnGm.classList.remove('active');
  }
}

// Direct Email / Gmail OTP login
let pendingAuthEmail = '';

async function handleSendEmailCode(e) {
  if (e) e.preventDefault();
  const input = document.getElementById('emailLoginInput');
  const btn = document.getElementById('emailSendCodeBtn');
  if (!input || !input.value.trim()) return;

  const email = input.value.trim().toLowerCase();
  pendingAuthEmail = email;

  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Отправка кода...';
  }

  try {
    const res = await fetchAPI('/auth/email/send-code', {
      method: 'POST',
      body: JSON.stringify({ email })
    });

    if (res.ok) {
      const sendForm = document.getElementById('emailSendCodeForm');
      const verifyForm = document.getElementById('emailVerifyCodeForm');
      const notif = document.getElementById('emailSentNotification');
      if (sendForm) sendForm.style.display = 'none';
      if (verifyForm) verifyForm.style.display = 'flex';

      if (res.data && res.data.test_code) {
        if (notif) {
          notif.innerHTML = `Код подтверждения: <strong>${res.data.test_code}</strong> (тестовый режим)`;
        }
        const codeInput = document.getElementById('emailCodeInput');
        if (codeInput) {
          codeInput.value = res.data.test_code;
        }
      } else if (notif) {
        notif.innerHTML = `Код подтверждения отправлен на <strong>${email}</strong>! Проверьте входящие или папку Спам.`;
      }
      const codeInput = document.getElementById('emailCodeInput');
      if (codeInput) codeInput.focus();
    } else {
      let msg = res.data && res.data.detail ? res.data.detail : 'Не удалось отправить код';
      alert('Ошибка: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)));
    }
  } catch (err) {
    alert('Сетевая ошибка при отправке кода подтверждения');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Получить код подтверждения ➔';
    }
  }
}

async function handleVerifyEmailCode(e) {
  if (e) e.preventDefault();
  const codeInput = document.getElementById('emailCodeInput');
  const btn = document.getElementById('emailVerifyBtn');
  if (!codeInput || !codeInput.value.trim()) return;

  const code = codeInput.value.trim();
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Проверка...';
  }

  try {
    const res = await fetchAPI('/auth/email/verify-code', {
      method: 'POST',
      body: JSON.stringify({
        email: pendingAuthEmail,
        code: code
      })
    });

    if (res.ok && res.data) {
      currentUser = res.data;
      updateUserUI();
      checkAndShowOnboarding();
      navigate('/app');
    } else {
      let msg = res.data && res.data.detail ? res.data.detail : 'Неверный или истекший код';
      alert('Ошибка авторизации: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)));
    }
  } catch (err) {
    alert('Сетевая ошибка при проверке кода');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Подтвердить и войти ➔';
    }
  }
}

function resetEmailAuth() {
  const sendForm = document.getElementById('emailSendCodeForm');
  const verifyForm = document.getElementById('emailVerifyCodeForm');
  if (sendForm) sendForm.style.display = 'flex';
  if (verifyForm) verifyForm.style.display = 'none';
  const input = document.getElementById('emailLoginInput');
  if (input) input.focus();
}

// Fallback direct email login
async function handleEmailLogin(e) {
  if (e) e.preventDefault();
  await handleSendEmailCode(e);
}

// Telegram & Google Login Widget Loader
async function initTelegramLoginWidget() {
  const container = document.getElementById('telegramLoginWidgetContainer');
  if (!container || container.dataset.loaded) return;
  container.dataset.loaded = 'true';

  let botUsername = 'nigerbbbit_bot';
  let googleClientId = '';
  try {
    const res = await fetchAPI('/auth/widget-config');
    if (res.ok && res.data) {
      if (res.data.bot_username) botUsername = res.data.bot_username;
      if (res.data.google_client_id) googleClientId = res.data.google_client_id;
    }
  } catch (err) {
    console.warn('Could not load widget config:', err);
  }

  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://telegram.org/js/telegram-widget.js?22';
  script.setAttribute('data-telegram-login', botUsername);
  script.setAttribute('data-size', 'large');
  script.setAttribute('data-radius', '12');
  script.setAttribute('data-onauth', 'onTelegramAuth(user)');
  script.setAttribute('data-request-access', 'write');
  container.innerHTML = '';
  container.appendChild(script);

  if (googleClientId) {
    initGoogleAuth(googleClientId);
  }
}

function initGoogleAuth(clientId) {
  const gContainer = document.getElementById('googleSignInContainer');
  if (!gContainer || gContainer.dataset.loaded) return;
  gContainer.dataset.loaded = 'true';

  const gScript = document.createElement('script');
  gScript.src = 'https://accounts.google.com/gsi/client';
  gScript.async = true;
  gScript.defer = true;
  gScript.onload = () => {
    if (window.google && window.google.accounts) {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: handleGoogleCredentialResponse
      });
      window.google.accounts.id.renderButton(gContainer, {
        theme: 'filled_black',
        size: 'large',
        shape: 'pill',
        text: 'signin_with',
        locale: 'ru'
      });
    }
  };
  document.head.appendChild(gScript);
}

// Callback for Google One Tap / Sign in with Google
if (typeof window !== 'undefined') {
  window.handleGoogleCredentialResponse = async function(response) {
    if (!response || !response.credential) return;
    const res = await fetchAPI('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential: response.credential })
    });
    if (res.ok) {
      currentUser = res.data;
      updateUserUI();
      checkAndShowOnboarding();
      navigate('/app');
    } else {
      alert('Ошибка авторизации через Google: ' + (res.data ? res.data.detail : 'Попробуйте снова'));
    }
  };

  // Callback for Telegram Login Widget
  window.onTelegramAuth = async function(user) {
    const res = await fetchAPI('/auth/telegram', {
      method: 'POST',
      body: JSON.stringify(user)
    });
    if (res.ok) {
      currentUser = res.data.user || res.data;
      updateUserUI();
      checkAndShowOnboarding();
      navigate('/app');
    } else {
      alert('Ошибка авторизации Telegram Widget: ' + (res.data ? res.data.detail : 'Попробуйте снова'));
    }
  };
}

async function handleLogout() {
  await fetchAPI('/auth/logout', { method: 'POST' });
  currentUser = null;
  updateUserUI();
  navigate('/app');
}

// ==========================================
// 1. DASHBOARD VIEW
// ==========================================
async function loadDashboard() {
  try {
    const [statsRes, profRes, anRes] = await Promise.all([
      fetchAPI('/stats'),
      fetchAPI('/profile'),
      fetchAPI('/profile/analytics')
    ]);

    // Accurate Due Count without 50-limit ceiling
    const dueCount = statsRes.ok && statsRes.data ? (statsRes.data.due_cards ?? 0) : 0;
    const dueEl = document.getElementById('dashDueCount');
    if (dueEl) dueEl.textContent = dueCount;

    // Daily Goal & Streak & Real Reviewed Today (in user timezone)
    if (profRes.ok && profRes.data) {
      const goal = profRes.data.daily_goal || 15;
      const streak = (statsRes.ok && statsRes.data && statsRes.data.streak_days !== undefined)
        ? statsRes.data.streak_days
        : (profRes.data.current_streak || 0);

      const streakBadge = document.getElementById('streakBadge');
      if (streakBadge) {
        streakBadge.style.display = 'inline-flex';
        streakBadge.textContent = `🔥 ${streak} дн`;
      }
      const dashStreak = document.getElementById('dashStreak');
      if (dashStreak) dashStreak.textContent = `${streak} дн`;

      // Real reviewed today count from backend database
      const reviewedToday = (statsRes.ok && statsRes.data && statsRes.data.reviewed_today !== undefined)
        ? statsRes.data.reviewed_today
        : ((anRes.ok && anRes.data && anRes.data.reviewed_today !== undefined) ? anRes.data.reviewed_today : 0);

      const goalProgress = document.getElementById('dashGoalProgress');
      const goalBar = document.getElementById('dashGoalBar');
      if (goalProgress) goalProgress.textContent = `${reviewedToday} / ${goal}`;
      if (goalBar) {
        const pct = Math.min(100, Math.round((reviewedToday / goal) * 100));
        goalBar.style.width = `${pct}%`;
      }
    }

    // Retention 30d
    if (anRes.ok && anRes.data) {
      const retEl = document.getElementById('dashRetention');
      if (retEl) {
        const rVal = anRes.data.retention_30d !== undefined ? anRes.data.retention_30d : 95.0;
        retEl.textContent = `${Number(rVal).toFixed(1)}%`;
      }
    }

    loadDashboardRecommendations();
    loadInteractiveQuiz();
  } catch (err) {
    console.error('Error loading dashboard:', err);
  }
}

async function loadDashboardRecommendations() {
  const container = document.getElementById('dashRecommendationsGrid');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--color-text-muted); padding: 24px;">Подбираем рекомендации на основе вашего уровня...</div>';

  const res = await fetchAPI('/profile/recommendations?limit=6');
  if (!res.ok || !Array.isArray(res.data) || res.data.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1;" class="empty-state">
        <div class="empty-title">Все рекомендации изучены</div>
        <div class="empty-desc">Отправьте новые слова или предложения боту в Telegram, чтобы пополнить рекомендации.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = res.data.map(item => {
    const w = item.word || item;
    const lemma = w.lemma || w.word || '';
    const trans = w.translation_ru || w.translation || '';
    const cefr = w.cefr_level || 'B1';
    const reason = (item.reasons && item.reasons.length) ? item.reasons.join(', ') : (item.reason || 'Оптимально для вашего словарного запаса');
    return `
    <div class="word-card">
      <div>
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <div class="word-lemma">${lemma}</div>
          <span class="cefr-pill">${cefr}</span>
        </div>
        <div class="word-trans">${trans}</div>
        <div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-top: 8px;">
          ${reason}
        </div>
      </div>
      <div style="margin-top: 16px; display: flex; gap: 8px;">
        <button class="btn btn-primary btn-sm" style="flex: 1;" onclick="addWordToDeck('${lemma.replace(/'/g, "\\'")}', '${trans.replace(/'/g, "\\'")}', '${cefr}', this)">
          В колоду
        </button>
        <button class="btn btn-secondary btn-sm" onclick="speakWord('${lemma.replace(/'/g, "\\'")}')" aria-label="Озвучить слово">
          🔊
        </button>
      </div>
    </div>
    `;
  }).join('');
}

async function addWordToDeck(lemma, translation, cefr, btn) {
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Добавление...';
  }

  const res = await fetchAPI('/words', {
    method: 'POST',
    body: JSON.stringify({
      text: lemma,
      lemma: lemma,
      translation_ru: translation,
      cefr_level: cefr || 'B1',
      source: 'recommendation'
    })
  });

  if (res.ok) {
    if (btn) {
      btn.textContent = 'В колоде ✓';
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-secondary');
    }
    showToast(`Слово "${lemma}" добавлено в колоду!`, 'success');
    if (typeof userDeckWordSet !== 'undefined') {
      userDeckWordSet.add(lemma.toLowerCase().trim());
      if (typeof document !== 'undefined') {
        document.querySelectorAll('.read-token').forEach(el => {
          const wordText = el.textContent.toLowerCase().replace(/[^a-z'-]/g, '');
          if (wordText === lemma.toLowerCase().trim()) {
            el.classList.add('in-deck');
          }
        });
      }
    }
  } else {
    let msg = 'Ошибка при добавлении слова';
    if (res.data) {
      if (typeof res.data.detail === 'string') {
        msg = res.data.detail;
      } else if (Array.isArray(res.data.detail) && res.data.detail.length > 0) {
        msg = res.data.detail.map(d => (typeof d === 'string' ? d : (d.msg || d.type || JSON.stringify(d)))).join(', ');
      } else if (typeof res.data.detail === 'object') {
        msg = JSON.stringify(res.data.detail);
      }
    }
    showToast('Не удалось добавить слово: ' + msg, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'В колоду';
    }
  }
}

// Sentence Extractor
async function handleAnalyzeSentence() {
  const input = document.getElementById('dashSentenceInput');
  const container = document.getElementById('dashSentenceResults');
  if (!input || !container) return;

  const text = input.value.trim();
  if (text.length < 5) {
    container.innerHTML = '<div style="color: var(--color-text-muted); font-size: 0.875rem;">Введите полное предложение на английском языке.</div>';
    return;
  }

  container.innerHTML = '<div style="color: var(--color-text-muted); font-size: 0.875rem; padding: 12px 0;">Анализируем предложение и выделяем лексику...</div>';

  const res = await fetchAPI('/sentences', {
    method: 'POST',
    body: JSON.stringify({ sentence: text })
  });

  if (!res.ok) {
    const errorMsg = (res.data && res.data.detail) ? res.data.detail : 'Сервис анализа предложений временно недоступен.';
    container.innerHTML = `
      <div style="background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 16px;">
        <div style="color: var(--color-danger); font-size: 0.875rem;">${errorMsg}</div>
      </div>
    `;
    return;
  }

  if (!res.data || !res.data.words || res.data.words.length === 0) {
    container.innerHTML = `
      <div style="background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 16px;">
        <div style="color: var(--color-text-secondary); font-size: 0.875rem;">Новых незнакомых слов в предложении не обнаружено или они уже есть в вашей колоде.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="margin-top: 12px;">
      <div style="font-size: 0.8125rem; font-weight: 600; color: var(--color-success); margin-bottom: 10px;">
        Найдено слов для изучения (${res.data.words.length}):
      </div>
      <div style="display: flex; flex-direction: column; gap: 8px;">
        ${res.data.words.map(w => `
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md);">
            <div>
              <strong style="font-size: 1rem;">${w.lemma}</strong>
              <span class="cefr-pill" style="margin-left: 8px;">${w.cefr_level || 'B2'}</span>
              <span style="color: var(--color-text-secondary); margin-left: 8px;">— ${w.translation_ru}</span>
              ${w.context_sentence ? `<div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-top: 4px;">«${w.context_sentence}»</div>` : ''}
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-primary btn-sm" onclick="addWordToDeck('${w.lemma.replace(/'/g, "\\'")}', '${w.translation_ru.replace(/'/g, "\\'")}', '${w.cefr_level}', this)">
                В колоду
              </button>
              <button class="btn btn-secondary btn-sm" onclick="speakWord('${w.lemma.replace(/'/g, "\\'")}')" aria-label="Озвучить">
                🔊
              </button>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

// Interactive Quiz Lab
async function loadInteractiveQuiz() {
  const container = document.getElementById('dashQuizContainer');
  if (!container) return;
  isSubmittingQuiz = false;

  container.innerHTML = '<div style="color: var(--color-text-muted); text-align: center; padding: 24px;">Загружаем вопрос квиза...</div>';

  const res = await fetchAPI('/quiz/multiple-choice');
  if (!res.ok || !res.data) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 24px 0;">
        <div class="empty-title">Для квиза нужно добавить слова</div>
        <div class="empty-desc">Добавьте хотя бы несколько слов через бота или из рекомендаций выше.</div>
      </div>
    `;
    return;
  }

  currentQuiz = res.data;

  container.innerHTML = `
    <div style="margin-bottom: 20px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 0.8125rem; font-weight: 500; color: var(--color-text-muted);">Тест на выбор значения</span>
        <span class="cefr-pill">${currentQuiz.cefr_level || 'B1'}</span>
      </div>
      <div style="display: flex; align-items: baseline; gap: 12px; margin: 10px 0;">
        <div style="font-size: 1.5rem; font-weight: 700;">${currentQuiz.lemma}</div>
        <button onclick="speakWord('${currentQuiz.lemma.replace(/'/g, "\\'")}')" style="background: none; border: none; cursor: pointer; color: var(--color-text-muted); font-size: 1.125rem;" aria-label="Озвучить">🔊</button>
      </div>
      ${currentQuiz.context_sentence ? `<div style="color: var(--color-text-secondary); font-size: 0.875rem; margin-bottom: 12px;">«${currentQuiz.context_sentence}»</div>` : ''}
      <div style="font-size: 0.8125rem; color: var(--color-text-muted);">Выберите подходящий перевод:</div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;" id="quizOptionsGrid">
      ${currentQuiz.options.map(opt => `
        <button class="btn btn-secondary quiz-option-btn" style="height: auto; padding: 12px 16px; text-align: left; justify-content: flex-start; white-space: normal;" onclick="submitQuizAnswer('${opt.replace(/'/g, "\\'")}', this)">
          ${opt}
        </button>
      `).join('')}
    </div>
    <div id="quizFeedbackContainer" style="margin-top: 16px;"></div>
  `;
}

async function submitQuizAnswer(chosenOption, btn) {
  if (!currentQuiz || isSubmittingQuiz) return;
  isSubmittingQuiz = true;

  // Immediately lock all options to prevent double-answering
  const optionButtons = document.querySelectorAll('#quizOptionsGrid button');
  optionButtons.forEach(b => {
    b.disabled = true;
    b.style.pointerEvents = 'none';
  });

  try {
    const res = await fetchAPI('/quiz/multiple-choice/answer', {
      method: 'POST',
      body: JSON.stringify({
        quiz_id: currentQuiz.quiz_id,
        chosen_option: chosenOption
      })
    });

    const feedback = document.getElementById('quizFeedbackContainer');
    if (res.ok && res.data) {
      const isCorrect = res.data.is_correct;
      if (btn) {
        if (isCorrect) {
          btn.style.borderColor = 'var(--color-success)';
          btn.style.background = 'var(--color-success-bg)';
          btn.style.color = 'var(--color-success)';
        } else {
          btn.style.borderColor = 'var(--color-danger)';
          btn.style.background = 'var(--color-danger-bg)';
          btn.style.color = 'var(--color-danger)';
        }
      }

      if (feedback) {
        feedback.innerHTML = `
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-radius: var(--radius-md); background: ${isCorrect ? 'var(--color-success-bg)' : 'var(--color-danger-bg)'}; border: 1px solid ${isCorrect ? 'var(--color-success-border)' : 'var(--color-danger-border)'};">
            <span style="font-size: 0.875rem; color: ${isCorrect ? 'var(--color-success)' : 'var(--color-danger)'};">
              ${isCorrect ? 'Верно!' : `Правильный ответ: <strong>${res.data.correct_answer}</strong>`}
            </span>
            <button class="btn btn-primary btn-sm" onclick="loadInteractiveQuiz()">Следующий →</button>
          </div>
        `;
      }
    } else {
      // Re-enable on error
      optionButtons.forEach(b => {
        b.disabled = false;
        b.style.pointerEvents = 'auto';
      });
      showToast('Не удалось отправить ответ квиза', 'error');
    }
  } finally {
    isSubmittingQuiz = false;
  }
}

// ==========================================
// 2. STUDY STUDIO (FSRS Active Recall)
// ==========================================
async function loadStudyQueue() {
  const container = document.getElementById('studyCardContainer');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--color-text-muted); text-align: center; padding: 60px 20px;">Подготовка очереди повторения FSRS...</div>';

  let url = '/cards/due?limit=25&interleave=true';
  if (studyTypeFilter && studyTypeFilter !== 'ALL') {
    url += `&card_type=${studyTypeFilter}`;
  }

  const res = await fetchAPI(url);
  if (!res.ok) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon" style="color: var(--color-danger);">⚠️</div>
        <h3 class="empty-title">Не удалось загрузить карточки</h3>
        <p class="empty-desc">Произошла сетевая ошибка при получении очереди повторения. Попробуйте повторить попытку.</p>
        <button class="btn btn-secondary btn-sm" onclick="loadStudyQueue()">Повторить попытку ↻</button>
      </div>
    `;
    return;
  }

  if (!Array.isArray(res.data) || res.data.length === 0) {
    let hasWords = true;
    try {
      const wordsCheck = await fetchAPI('/words?page=1&page_size=1');
      if (wordsCheck.ok && wordsCheck.data && wordsCheck.data.total === 0) {
        hasWords = false;
      }
    } catch (_) {}

    if (!hasWords) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📖</div>
          <h3 class="empty-title">В вашей колоде пока нет слов</h3>
          <p class="empty-desc">
            Отправьте первое слово боту в Telegram или добавьте полезные слова из рекомендаций на дашборде.
          </p>
          <div style="display: flex; gap: var(--space-3); justify-content: center; flex-wrap: wrap; margin-top: var(--space-4);">
            <a href="https://t.me/nigerbbbit_bot" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm">Открыть Telegram-бота ➔</a>
            <button class="btn btn-secondary btn-sm" onclick="navigate('/app')">К рекомендациям слов</button>
          </div>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">✓</div>
        <h3 class="empty-title">Все карточки на сегодня повторены!</h3>
        <p class="empty-desc">
          Интервалы FSRS пересчитаны. Новые повторения появятся согласно вашей индивидуальной кривой забывания.
        </p>
        <button class="btn btn-primary btn-sm" onclick="navigate('/app/words')">Посмотреть колоду слов ➔</button>
      </div>
    `;
    return;
  }

  studyQueueManager.setQueue(res.data);
  studyQueue = studyQueueManager.getQueue();
  studyIndex = studyQueueManager.getIndex();
  isAnswerRevealed = studyQueueManager.isAnswerRevealed();
  renderCurrentStudyCard();
}

function setStudyTypeFilter(type) {
  studyTypeFilter = type;
  studyQueueManager.setFilter(type);
  studyIndex = studyQueueManager.getIndex();
  document.querySelectorAll('.studio-tab').forEach(t => {
    t.classList.toggle('active', t.getAttribute('data-type') === type);
  });
  loadStudyQueue();
}

function renderCurrentStudyCard() {
  const container = document.getElementById('studyCardContainer');
  if (!container) return;

  if (studyIndex >= studyQueue.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">★</div>
        <h3 class="empty-title">Сессия повторения завершена!</h3>
        <p class="empty-desc">Вы повторили ${studyQueue.length} карточек. Прогресс сохранен в FSRS.</p>
        <button class="btn btn-primary btn-sm" onclick="navigate('/app')">Вернуться в дашборд ➔</button>
      </div>
    `;
    return;
  }

  const card = studyQueue[studyIndex];
  const word = card.word || {};
  const cType = card.card_type;

  let frontHtml = '';
  let backHtml = '';

  if (cType === 'en_ru') {
    frontHtml = `
      <div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-bottom: 8px;">Прямой перевод (EN ➔ RU)</div>
      <div style="font-size: 2rem; font-weight: 700; color: var(--color-text-primary); margin-bottom: 12px;">
        ${word.lemma || ''}
      </div>
      ${word.example ? `<div style="color: var(--color-text-secondary); font-size: 0.9375rem;">«${word.example.sentence_en}»</div>` : ''}
    `;
    backHtml = `
      <div style="font-size: 1.25rem; font-weight: 600; color: var(--color-success); margin-bottom: 8px;">
        ${word.translation_ru || ''}
      </div>
      ${word.example && word.example.sentence_ru ? `<div style="color: var(--color-text-secondary); font-size: 0.875rem;">«${word.example.sentence_ru}»</div>` : ''}
      ${word.grammar_note ? `<div style="font-size: 0.8125rem; color: var(--color-warning); margin-top: 8px;">💡 ${word.grammar_note}</div>` : ''}
    `;
  } else if (cType === 'ru_en') {
    frontHtml = `
      <div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-bottom: 8px;">Активное воспроизведение (RU ➔ EN)</div>
      <div style="font-size: 1.75rem; font-weight: 700; color: var(--color-text-primary); margin-bottom: 12px;">
        ${word.translation_ru || ''}
      </div>
      ${word.example && word.example.sentence_ru ? `<div style="color: var(--color-text-secondary); font-size: 0.9375rem;">«${word.example.sentence_ru}»</div>` : ''}
    `;
    backHtml = `
      <div style="font-size: 1.75rem; font-weight: 700; color: var(--color-text-primary); margin-bottom: 8px; display: flex; align-items: center; justify-content: center; gap: 12px;">
        <span>${word.lemma || ''}</span>
        <button onclick="speakWord('${(word.lemma || '').replace(/'/g, "\\'")}')" style="background: none; border: none; cursor: pointer; color: var(--color-text-muted); font-size: 1.25rem;">🔊</button>
      </div>
      ${word.transcription ? `<div style="color: var(--color-text-muted); font-family: var(--font-mono); font-size: 0.875rem; margin-bottom: 8px;">[${word.transcription}]</div>` : ''}
      ${word.example ? `<div style="color: var(--color-text-secondary); font-size: 0.875rem;">«${word.example.sentence_en}»</div>` : ''}
    `;
  } else if (cType === 'cloze') {
    const clozeEn = word.example && word.example.sentence_en
      ? word.example.sentence_en.replace(new RegExp(`\\b${word.lemma}\\b`, 'i'), '【 ... 】')
      : `Complete the sentence with: 【 ... 】`;
    frontHtml = `
      <div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-bottom: 8px;">Заполните пропуск в предложении</div>
      <div style="font-size: 1.25rem; font-weight: 600; line-height: 1.5; margin-bottom: 16px;">
        ${clozeEn}
      </div>
      <div style="color: var(--color-text-secondary); font-size: 0.875rem;">Значение: ${word.translation_ru || ''}</div>
    `;
    backHtml = `
      <div style="font-size: 1.5rem; font-weight: 700; color: var(--color-success); margin-bottom: 8px;">
        ${word.lemma || ''}
      </div>
      ${word.example ? `<div style="font-size: 0.9375rem; color: var(--color-text-primary);">«${word.example.sentence_en}»</div>` : ''}
    `;
  } else {
    // Audio type
    frontHtml = `
      <div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-bottom: 8px;">Восприятие на слух</div>
      <div style="margin: 20px 0;">
        <button class="btn btn-secondary btn-lg" onclick="speakWord('${(word.lemma || '').replace(/'/g, "\\'")}')">
          🔊 Прослушать слово
        </button>
      </div>
      <div style="color: var(--color-text-muted); font-size: 0.8125rem;">Постарайтесь понять значение без зрительной опоры</div>
    `;
    backHtml = `
      <div style="font-size: 1.75rem; font-weight: 700; color: var(--color-text-primary); margin-bottom: 6px;">
        ${word.lemma || ''}
      </div>
      <div style="font-size: 1.125rem; color: var(--color-success); margin-bottom: 10px;">
        ${word.translation_ru || ''}
      </div>
      ${word.example ? `<div style="color: var(--color-text-secondary); font-size: 0.875rem;">«${word.example.sentence_en}»</div>` : ''}
    `;
  }

  container.innerHTML = `
    <div class="flashcard-inner" onclick="handleCardClick(event)">
      <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; margin-bottom: 16px; font-size: 0.8125rem; color: var(--color-text-muted);">
        <div>Карточка ${studyIndex + 1} из ${studyQueue.length}</div>
        <div style="display: flex; gap: 6px; align-items: center;">
          <span class="cefr-pill">${word.cefr_level || 'B1'}</span>
        </div>
      </div>

      <!-- Front Face -->
      <div style="padding: 16px 0; min-height: 100px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
        ${frontHtml}
      </div>

      <!-- Back Face -->
      <div id="cardBackFace" style="display: ${isAnswerRevealed ? 'block' : 'none'}; width: 100%; border-top: 1px solid var(--color-border); padding-top: 20px; margin-top: 16px;">
        ${backHtml}

        <!-- Rating Buttons (1 to 4) -->
        <div class="rating-grid">
          <button class="rating-btn" onclick="submitCardRating(${card.id}, 1); event.stopPropagation();">
            <span class="rating-key">1</span>
            <span class="rating-title" style="color: var(--color-danger);">Снова</span>
            <span class="rating-desc">Забыл</span>
          </button>
          <button class="rating-btn" onclick="submitCardRating(${card.id}, 2); event.stopPropagation();">
            <span class="rating-key">2</span>
            <span class="rating-title" style="color: var(--color-warning);">Трудно</span>
            <span class="rating-desc">С усилием</span>
          </button>
          <button class="rating-btn" onclick="submitCardRating(${card.id}, 3); event.stopPropagation();">
            <span class="rating-key">3</span>
            <span class="rating-title" style="color: var(--color-success);">Хорошо</span>
            <span class="rating-desc">Вспомнил</span>
          </button>
          <button class="rating-btn" onclick="submitCardRating(${card.id}, 4); event.stopPropagation();">
            <span class="rating-key">4</span>
            <span class="rating-title" style="color: var(--color-primary);">Легко</span>
            <span class="rating-desc">Помню отлично</span>
          </button>
        </div>
      </div>

      <div id="revealBtnContainer" style="display: ${isAnswerRevealed ? 'none' : 'flex'}; margin-top: 24px;">
        <button class="btn btn-primary btn-sm" onclick="revealCardAnswer(); event.stopPropagation();">
          Показать ответ (Space) ➔
        </button>
      </div>
    </div>
  `;
}

function handleCardClick(e) {
  if (!isAnswerRevealed && !e.target.closest('button')) {
    revealCardAnswer();
  }
}

function revealCardAnswer() {
  studyQueueManager.revealAnswer();
  isAnswerRevealed = true;
  const backFace = document.getElementById('cardBackFace');
  const revealBtn = document.getElementById('revealBtnContainer');
  if (backFace) backFace.style.display = 'block';
  if (revealBtn) revealBtn.style.display = 'none';
}

async function submitCardRating(cardId, rating) {
  if (!studyQueueManager.startSubmit()) return;

  const ratingButtons = document.querySelectorAll('.rating-btn');
  ratingButtons.forEach(b => {
    b.disabled = true;
    b.style.pointerEvents = 'none';
  });

  const res = await fetchAPI(`/cards/${cardId}/review`, {
    method: 'POST',
    body: JSON.stringify({ rating: rating })
  });

  if (res.ok || res.status === 409) {
    studyQueueManager.finishSubmitSuccess();
    studyIndex = studyQueueManager.getIndex();
    isAnswerRevealed = studyQueueManager.isAnswerRevealed();
    renderCurrentStudyCard();
  } else {
    // Network or server error: DO NOT advance queue!
    studyQueueManager.finishSubmitFailure();
    ratingButtons.forEach(b => {
      b.disabled = false;
      b.style.pointerEvents = 'auto';
    });
    showToast('Не удалось сохранить ответ. Попробуйте еще раз.', 'error');
  }
}

// Global hotkeys for study studio
if (typeof document !== 'undefined') {
  document.addEventListener('keydown', (e) => {
    if (currentRoute !== '/app/study' || !studyQueue.length || studyIndex >= studyQueue.length) return;
    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;

    if (e.code === 'Space') {
      e.preventDefault();
      if (!isAnswerRevealed) revealCardAnswer();
    } else if (isAnswerRevealed) {
      const card = studyQueue[studyIndex];
      if (e.key === '1') submitCardRating(card.id, 1);
      if (e.key === '2') submitCardRating(card.id, 2);
      if (e.key === '3') submitCardRating(card.id, 3);
      if (e.key === '4') submitCardRating(card.id, 4);
    }
  });
}

// ==========================================
// 3. WORDS DECK VIEW
// ==========================================
async function loadWordsDeck() {
  const container = document.getElementById('wordsGridContainer');
  const pagination = document.getElementById('wordsPagination');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--color-text-muted); padding: 40px; text-align: center; grid-column: 1 / -1;">Загрузка колоды слов...</div>';

  let url = `/words?page=${wordsState.page}&page_size=${wordsState.pageSize}`;
  if (wordsState.query) url += `&q=${encodeURIComponent(wordsState.query)}`;
  if (wordsState.cefr !== 'ALL') url += `&cefr_level=${wordsState.cefr}`;
  if (wordsState.status !== 'ALL') url += `&status=${wordsState.status}`;

  const res = await fetchAPI(url);
  if (!res.ok || !res.data) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1;" class="empty-state">
        <div class="empty-icon" style="color: var(--color-danger);">⚠️</div>
        <h3 class="empty-title">Не удалось загрузить слова</h3>
        <p class="empty-desc">Произошла сетевая ошибка при обращении к серверу. Попробуйте повторить запрос.</p>
        <button class="btn btn-secondary btn-sm" onclick="loadWordsDeck()">Повторить попытку ↻</button>
      </div>
    `;
    if (pagination) pagination.innerHTML = '';
    return;
  }

  const items = res.data.items || [];
  wordsState.total = res.data.total || 0;

  if (items.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1;" class="empty-state">
        <div class="empty-icon">📂</div>
        <h3 class="empty-title">Слов пока не найдено</h3>
        <p class="empty-desc">Отправьте незнакомое слово боту в Telegram или импортируйте CSV файл.</p>
      </div>
    `;
    if (pagination) pagination.innerHTML = '';
    return;
  }

  container.innerHTML = items.map(w => `
    <div class="word-card" id="wordCard-${w.id}">
      <div>
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <div class="word-lemma">${w.lemma}</div>
          <span class="cefr-pill">${w.cefr_level || 'B1'}</span>
        </div>
        <div class="word-trans">${w.translation_ru}</div>
        ${w.notes ? `<div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-top: 6px;">📝 ${w.notes}</div>` : ''}
      </div>

      <div style="margin-top: 14px; border-top: 1px solid var(--color-border); padding-top: 10px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
        <select class="select-field" style="height: 32px; font-size: 0.75rem; padding: 0 8px; width: 110px;" onchange="handleWordStatusChange(${w.id}, this.value)">
          <option value="learning" ${w.status === 'learning' ? 'selected' : ''}>Изучается</option>
          <option value="mastered" ${w.status === 'mastered' ? 'selected' : ''}>Освоено</option>
        </select>

        <div style="display: flex; gap: 6px;">
          <button class="btn btn-secondary btn-sm" style="height: 32px; padding: 0 8px;" title="Озвучить" onclick="speakWord('${w.lemma.replace(/'/g, "\\'")}')">🔊</button>
          <button class="btn btn-secondary btn-sm" style="height: 32px; padding: 0 8px; color: var(--color-danger);" title="Удалить из колоды" onclick="handleDeleteWord(${w.id})">🗑️</button>
        </div>
      </div>
    </div>
  `).join('');

  renderWordsPagination();
}

function renderWordsPagination() {
  const container = document.getElementById('wordsPagination');
  if (!container) return;

  const totalPages = Math.ceil(wordsState.total / wordsState.pageSize) || 1;
  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }

  let html = '';
  if (wordsState.page > 1) {
    html += `<button class="btn btn-secondary btn-sm" onclick="goToWordsPage(${wordsState.page - 1})">◀ Назад</button>`;
  }
  html += `<span style="font-size: 0.8125rem; color: var(--color-text-secondary); padding: 8px 12px;">Стр. ${wordsState.page} из ${totalPages} (${wordsState.total} слов)</span>`;
  if (wordsState.page < totalPages) {
    html += `<button class="btn btn-secondary btn-sm" onclick="goToWordsPage(${wordsState.page + 1})">Вперед ▶</button>`;
  }

  container.innerHTML = html;
}

function goToWordsPage(page) {
  wordsState.page = page;
  loadWordsDeck();
}

function handleWordsSearch(val) {
  clearTimeout(wordsState.searchTimer);
  wordsState.searchTimer = setTimeout(() => {
    wordsState.query = val.trim();
    wordsState.page = 1;
    loadWordsDeck();
  }, 300);
}

function setWordsCefrFilter(cefr, btn) {
  wordsState.cefr = cefr;
  wordsState.page = 1;
  document.querySelectorAll('[data-cefr]').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadWordsDeck();
}

function setWordsStatusFilter(status, btn) {
  wordsState.status = status;
  wordsState.page = 1;
  document.querySelectorAll('[data-status]').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadWordsDeck();
}

async function handleWordStatusChange(wordId, newStatus) {
  await fetchAPI(`/words/${wordId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: newStatus })
  });
}

async function handleDeleteWord(wordId) {
  if (!confirm('Удалить это слово и все связанные карточки из вашей колоды?')) return;
  const res = await fetchAPI(`/words/${wordId}`, { method: 'DELETE' });
  if (res.ok) {
    const cardEl = document.getElementById(`wordCard-${wordId}`);
    if (cardEl) cardEl.remove();
    loadWordsDeck();
  }
}

// CSV Import & Export
async function handleCsvUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  const res = await fetchAPI('/words/import', {
    method: 'POST',
    body: formData
  });

  input.value = '';

  if (res.ok && res.data) {
    alert(`Импорт завершен!\nУспешно добавлено: ${res.data.imported_count} слов\nПропущено дубликатов: ${res.data.skipped_duplicates}`);
    wordsState.page = 1;
    loadWordsDeck();
  } else {
    alert('Ошибка импорта CSV: ' + (res.data ? res.data.detail : 'Проверьте формат'));
  }
}

async function handleCsvExport() {
  const res = await fetchAPI('/words?page=1&page_size=1000');
  if (!res.ok || !res.data || !res.data.items) {
    alert('Не удалось сформировать экспорт');
    return;
  }

  const items = res.data.items;
  let csv = 'lemma,translation_ru,cefr_level,status,notes\n';
  items.forEach(w => {
    const lemma = `"${(w.lemma || '').replace(/"/g, '""')}"`;
    const trans = `"${(w.translation_ru || '').replace(/"/g, '""')}"`;
    const cefr = w.cefr_level || '';
    const status = w.status || 'learning';
    const notes = `"${(w.notes || '').replace(/"/g, '""')}"`;
    csv += `${lemma},${trans},${cefr},${status},${notes}\n`;
  });

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `eng_tutor_words_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function handleAnkiExport() {
  const res = await fetchAPI('/words?page=1&page_size=1000');
  if (!res.ok || !res.data || !res.data.items) {
    alert('Не удалось сформировать экспорт для Anki');
    return;
  }

  const items = res.data.items;
  let txt = '#separator:tab\n#html:false\n#tags column:3\n';
  items.forEach(w => {
    const front = (w.lemma || '').replace(/\t/g, ' ');
    const back = `${w.translation_ru || ''}`.replace(/\t/g, ' ');
    const tag = `CEFR_${w.cefr_level || 'B1'}`;
    txt += `${front}\t${back}\t${tag}\n`;
  });

  const blob = new Blob([txt], { type: 'text/plain;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `eng_tutor_anki_${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ==========================================
// 4. ANALYTICS VIEW
// ==========================================
async function loadAnalytics() {
  const chartContainer = document.getElementById('retentionChartSvgContainer');
  const cardTypesContainer = document.getElementById('cardTypesAnalyticsList');
  const forecastContainer = document.getElementById('forecastChartContainer');
  const problemContainer = document.getElementById('problemWordsList');
  const scoreBadge = document.getElementById('an30dRetentionScore');

  if (chartContainer) chartContainer.innerHTML = '<div style="color: var(--color-text-muted);">Загрузка аналитики...</div>';

  const res = await fetchAPI('/profile/analytics');
  if (!res.ok || !res.data) {
    if (chartContainer) {
      chartContainer.innerHTML = `
        <div style="padding: 24px 0; text-align: center;">
          <div style="color: var(--color-danger); margin-bottom: 8px;">Не удалось загрузить данные аналитики.</div>
          <button class="btn btn-secondary btn-sm" onclick="loadAnalytics()">Повторить попытку ↻</button>
        </div>
      `;
    }
    return;
  }

  const an = res.data;

  if (scoreBadge) {
    const rVal = an.retention_30d !== undefined ? an.retention_30d : 95.0;
    scoreBadge.textContent = `Удержание: ${Number(rVal).toFixed(1)}%`;
  }

  // 1. Retention SVG Chart
  if (chartContainer && an.retention_daily) {
    renderRetentionSvgChart(chartContainer, an.retention_daily);
  }

  // 2. Card Types Accuracy
  const breakdownList = an.card_types_breakdown || [];
  const breakdownMap = {};
  breakdownList.forEach(item => {
    breakdownMap[item.card_type] = item.accuracy_pct;
  });

  if (cardTypesContainer) {
    const types = [
      { key: 'en_ru', label: 'Прямой перевод (EN → RU)' },
      { key: 'ru_en', label: 'Активное воспроизведение (RU → EN)' },
      { key: 'cloze', label: 'Пропуск в контексте (Cloze)' },
      { key: 'audio', label: 'Восприятие на слух (Audio)' }
    ];
    cardTypesContainer.innerHTML = types.map(t => {
      const acc = (an.card_type_accuracy && an.card_type_accuracy[t.key] !== undefined)
        ? an.card_type_accuracy[t.key]
        : (breakdownMap[t.key] !== undefined ? breakdownMap[t.key] : 100);
      return `
        <div>
          <div style="display: flex; justify-content: space-between; font-size: 0.8125rem; margin-bottom: 4px;">
            <span style="color: var(--color-text-secondary);">${t.label}</span>
            <span style="font-weight: 600; color: var(--color-text-primary);">${Number(acc).toFixed(1)}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill" style="width: ${acc}%;"></div>
          </div>
        </div>
      `;
    }).join('');
  }

  // 3. 7-Day Workload Forecast
  const forecastList = an.workload_forecast_7d || an.forecast_7d || [];
  if (forecastContainer && forecastList.length) {
    const maxVal = Math.max(1, ...forecastList.map(d => d.due_cards_count !== undefined ? d.due_cards_count : (d.due_count || 0)));
    forecastContainer.innerHTML = forecastList.map(d => {
      const count = d.due_cards_count !== undefined ? d.due_cards_count : (d.due_count || 0);
      const heightPct = Math.round((count / maxVal) * 100);
      const dayLabel = d.date.slice(5);
      return `
        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; justify-content: flex-end;">
          <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted);">${count}</div>
          <div style="width: 100%; background: var(--color-primary); border-radius: 4px; height: ${Math.max(8, heightPct)}%;"></div>
          <div style="font-size: 0.6875rem; color: var(--color-text-muted);">${dayLabel}</div>
        </div>
      `;
    }).join('');
  }

  // 4. Problem Words
  if (problemContainer && an.problem_words) {
    if (an.problem_words.length === 0) {
      problemContainer.innerHTML = '<div style="color: var(--color-text-muted); font-size: 0.875rem;">Слов с частыми ошибками нет. Отличный результат!</div>';
    } else {
      problemContainer.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 8px;">
          ${an.problem_words.map(pw => `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md);">
              <div>
                <strong style="font-size: 0.9375rem;">${pw.lemma}</strong>
                <span style="color: var(--color-text-secondary); font-size: 0.8125rem; margin-left: 8px;">— ${pw.translation_ru}</span>
              </div>
              <div style="display: flex; gap: 12px; align-items: center; font-size: 0.8125rem;">
                <span style="color: var(--color-danger);">Ошибок: ${pw.lapses}</span>
                <span style="color: var(--color-text-muted);">Стабильность: ${Number(pw.stability || 0).toFixed(1)}д</span>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }
  }
}

function renderRetentionSvgChart(container, dailyData) {
  if (!dailyData || dailyData.length === 0) {
    container.innerHTML = '<div style="color: var(--color-text-muted); padding: 20px 0; text-align: center;">Недостаточно данных для графика.</div>';
    return;
  }

  const width = 800;
  const height = 140;
  const padLeft = 36;
  const padRight = 16;
  const padTop = 10;
  const padBottom = 20;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  const points = dailyData.map((d, idx) => {
    const denom = Math.max(1, dailyData.length - 1);
    const x = padLeft + (idx / denom) * chartW;
    const rawRate = Number(d.retention_pct !== undefined ? d.retention_pct : d.retention_rate);
    const rate = (!isNaN(rawRate) && isFinite(rawRate)) ? Math.max(0, Math.min(100, rawRate)) : 100;
    const y = padTop + chartH - (rate / 100) * chartH;
    return {
      x: isNaN(x) ? padLeft : x,
      y: isNaN(y) ? (padTop + chartH) : y,
      rate,
      date: d.date || ''
    };
  });

  const polylineStr = points.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" style="width: 100%; height: 100%; overflow: visible;">
      <!-- Grid lines -->
      <line x1="${padLeft}" y1="${padTop}" x2="${width - padRight}" y2="${padTop}" stroke="var(--color-border)" stroke-dasharray="3 3"/>
      <line x1="${padLeft}" y1="${padTop + chartH * 0.5}" x2="${width - padRight}" y2="${padTop + chartH * 0.5}" stroke="var(--color-border)" stroke-dasharray="3 3"/>
      <line x1="${padLeft}" y1="${padTop + chartH}" x2="${width - padRight}" y2="${padTop + chartH}" stroke="var(--color-border)"/>

      <!-- Labels -->
      <text x="${padLeft - 6}" y="${padTop + 4}" fill="var(--color-text-muted)" font-size="10" text-anchor="end">100%</text>
      <text x="${padLeft - 6}" y="${padTop + chartH * 0.5 + 4}" fill="var(--color-text-muted)" font-size="10" text-anchor="end">50%</text>
      <text x="${padLeft - 6}" y="${padTop + chartH + 4}" fill="var(--color-text-muted)" font-size="10" text-anchor="end">0%</text>

      <!-- Curve Line -->
      <polyline fill="none" stroke="var(--color-primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="${polylineStr}" />

      <!-- Dots -->
      ${points.map(p => `
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="var(--color-surface)" stroke="var(--color-primary)" stroke-width="2">
          <title>${p.date}: ${p.rate}%</title>
        </circle>
      `).join('')}
    </svg>
  `;
}

// ==========================================
// 5. PROFILE VIEW
// ==========================================
async function loadProfile() {
  const res = await fetchAPI('/profile');
  if (!res.ok || !res.data) return;

  const p = res.data;
  const cefrSelect = document.getElementById('profCefrSelect');
  const goalInput = document.getElementById('profDailyGoalInput');
  const tzInput = document.getElementById('profTimezoneInput');
  const remInput = document.getElementById('profReminderHourInput');
  const emailInput = document.getElementById('profEmailInput');

  if (cefrSelect) cefrSelect.value = p.cefr_level || 'B1';
  if (goalInput) goalInput.value = p.daily_goal || 15;
  if (tzInput) tzInput.value = p.timezone || 'UTC';
  if (remInput) remInput.value = p.reminder_hour !== null && p.reminder_hour !== undefined ? p.reminder_hour : '';
  if (emailInput) emailInput.value = p.email || '';

  const activeTypes = p.active_card_types || ['en_ru', 'ru_en', 'cloze', 'audio'];
  ['en_ru', 'ru_en', 'cloze', 'audio'].forEach(t => {
    const cb = document.getElementById(`type_${t}`);
    if (cb) cb.checked = activeTypes.includes(t);
  });
}

async function handleSaveProfile(e) {
  e.preventDefault();

  const activeTypes = [];
  ['en_ru', 'ru_en', 'cloze', 'audio'].forEach(t => {
    const cb = document.getElementById(`type_${t}`);
    if (cb && cb.checked) activeTypes.push(t);
  });

  const payload = {
    cefr_level: document.getElementById('profCefrSelect').value,
    daily_goal: parseInt(document.getElementById('profDailyGoalInput').value, 10) || 15,
    timezone: document.getElementById('profTimezoneInput').value.trim() || 'UTC',
    email: document.getElementById('profEmailInput').value.trim() || null,
    active_card_types: activeTypes.length ? activeTypes : ['en_ru', 'ru_en']
  };

  const remVal = document.getElementById('profReminderHourInput').value;
  if (remVal !== '') {
    payload.reminder_hour = parseInt(remVal, 10);
  }

  const res = await fetchAPI('/profile', {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });

  if (res.ok) {
    alert('Настройки профиля сохранены.');
  } else {
    alert('Ошибка при сохранении: ' + (res.data ? res.data.detail : 'Проверьте поля'));
  }
}

// ==========================================
// 6. ONBOARDING (First Login Setup)
// ==========================================
const onboardingState = {
  cefr: 'B1',
  goal: 15,
  hour: 19
};

function checkAndShowOnboarding() {
  if (!currentUser) return;
  const done = localStorage.getItem('eng_onboarding_completed');
  const modal = document.getElementById('onboardingModal');
  if (!done && modal) {
    modal.style.display = 'flex';
  }
}

function selectOnboardingCefr(cefr, el) {
  onboardingState.cefr = cefr;
  document.querySelectorAll('.onb-cefr').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
}

function selectOnboardingGoal(goal, el) {
  onboardingState.goal = Number(goal);
  document.querySelectorAll('.onb-goal').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
}

async function handleSaveOnboarding(e) {
  if (e) e.preventDefault();
  const hourSelect = document.getElementById('onboardingReminderHour');
  const hour = hourSelect ? parseInt(hourSelect.value, 10) : 19;
  onboardingState.hour = isNaN(hour) ? 19 : hour;

  try {
    await fetchAPI('/profile', {
      method: 'PATCH',
      body: JSON.stringify({
        cefr_level: onboardingState.cefr,
        daily_goal: onboardingState.goal,
        reminder_hour: onboardingState.hour
      })
    });
  } catch (err) {
    console.warn('Failed to save onboarding settings:', err);
  }

  localStorage.setItem('eng_onboarding_completed', 'true');
  const modal = document.getElementById('onboardingModal');
  if (modal) modal.style.display = 'none';

  if (currentRoute === '/app') {
    loadDashboard();
  }
}

function skipOnboarding() {
  localStorage.setItem('eng_onboarding_completed', 'true');
  const modal = document.getElementById('onboardingModal');
  if (modal) modal.style.display = 'none';
}

// ==========================================
// 6. READING STUDIO (/app/reading)
// ==========================================
const READING_PRESETS = {
  habits: {
    title: "The Science of Habits",
    cefr: "B1",
    text: `Building meaningful habits requires deliberate consistency rather than extraordinary motivation. According to cognitive neuroscience, repetitive behaviors gradually form strong neural pathways in the human brain.

When you perform an action repeatedly in response to a specific contextual cue, the basal ganglia takes over the execution. Over time, this natural neurological transition substantially reduces the cognitive effort needed to sustain the routine, turning complex tasks into automatic actions.`
  },
  ai_tech: {
    title: "How Neural Networks Understand Language",
    cefr: "B2",
    text: `Modern language models do not memorize sentences word by word. Instead, they transform words into high-dimensional numerical vectors known as embeddings. In this continuous mathematical space, concepts with similar contextual meanings reside exceptionally close to each other.

Transformer architectures utilize attention mechanisms to evaluate which surrounding tokens are most relevant to every other term in a paragraph. This sophisticated mathematical representation allows machines to comprehend nuances, summarize technical documents, and translate between human languages.`
  },
  space: {
    title: "Deep Space Exploration",
    cefr: "B2",
    text: `Human exploration of deep space represents one of the most ambitious engineering endeavors in modern history. Robotic probes equipped with autonomous navigation algorithms venture billions of kilometers beyond Earth, transmitting unprecedented astronomical observations back across the solar system.

To establish permanent human settlements on distant celestial bodies, scientists must overcome formidable challenges, including cosmic radiation, microgravity health effects, and closed-loop life support systems.`
  }
};

const QUICK_DICT = {
  habits: { ru: "привычки", cefr: "A2" },
  habit: { ru: "привычка", cefr: "A2" },
  deliberate: { ru: "осознанный, намеренный", cefr: "B2" },
  consistency: { ru: "постоянство, последовательность", cefr: "B2" },
  motivation: { ru: "мотивация", cefr: "B1" },
  cognitive: { ru: "когнитивный, познавательный", cefr: "B2" },
  neuroscience: { ru: "нейронаука", cefr: "C1" },
  pathways: { ru: "пути, нейронные цепочки", cefr: "B2" },
  pathway: { ru: "путь, связь", cefr: "B2" },
  neural: { ru: "нейронный, нервный", cefr: "B2" },
  substantially: { ru: "существенно, значительно", cefr: "B2" },
  execution: { ru: "выполнение, исполнение", cefr: "B2" },
  transition: { ru: "переход", cefr: "B2" },
  sustain: { ru: "поддерживать, сохранять", cefr: "B2" },
  routine: { ru: "рутина, привычный распорядок", cefr: "B1" },
  automatic: { ru: "автоматический", cefr: "A2" },
  vectors: { ru: "векторы", cefr: "B2" },
  embeddings: { ru: "векторные представления (эмбеддинги)", cefr: "C1" },
  continuous: { ru: "непрерывный", cefr: "B2" },
  contextual: { ru: "контекстуальный", cefr: "B2" },
  mechanisms: { ru: "механизмы", cefr: "B2" },
  evaluate: { ru: "оценивать", cefr: "B2" },
  sophisticated: { ru: "передовой, комплексный", cefr: "B2" },
  comprehend: { ru: "понимать, постигать", cefr: "B2" },
  exploration: { ru: "исследование, освоение", cefr: "B1" },
  endeavors: { ru: "начинания, стремления", cefr: "C1" },
  endeavor: { ru: "начинание, попытка", cefr: "C1" },
  autonomous: { ru: "автономный", cefr: "B2" },
  navigation: { ru: "навигация", cefr: "B1" },
  unprecedented: { ru: "беспрецедентный", cefr: "C1" },
  observations: { ru: "наблюдения", cefr: "B2" },
  settlements: { ru: "поселения", cefr: "B2" },
  challenges: { ru: "трудности, вызовы", cefr: "B1" },
  radiation: { ru: "излучение, радиация", cefr: "B2" },
  furthermore: { ru: "более того, кроме того", cefr: "B2" },
  consequently: { ru: "следовательно", cefr: "B2" }
};

let currentReadingText = READING_PRESETS.habits.text;
let currentActiveToken = null;
let readingPopoverListenerAdded = false;
let userDeckWordSet = new Set();

async function syncUserDeckWords() {
  try {
    const res = await fetchAPI('/words?page=1&page_size=100', { silent: true });
    if (res.ok && res.data && res.data.items) {
      userDeckWordSet = new Set(res.data.items.map(it => (it.lemma || '').toLowerCase().trim()));
    }
  } catch (err) {
    console.debug('Could not sync user deck words:', err);
  }
}

async function loadReading() {
  await syncUserDeckWords();
  loadReadingPreset('habits');
  if (!readingPopoverListenerAdded && typeof document !== 'undefined') {
    document.addEventListener('click', onDocumentClickReadingPopover);
    readingPopoverListenerAdded = true;
  }
}

function onDocumentClickReadingPopover(e) {
  const popover = document.getElementById('readingWordPopover');
  if (!popover || popover.style.display === 'none') return;
  if (!popover.contains(e.target) && !e.target.classList.contains('read-token')) {
    hideReadingPopover();
  }
}

function hideReadingPopover() {
  const popover = document.getElementById('readingWordPopover');
  if (popover) popover.style.display = 'none';
  if (currentActiveToken) {
    currentActiveToken.classList.remove('active-token');
    currentActiveToken = null;
  }
}

function toggleReadingGenerator(btn) {
  const genBox = document.getElementById('readingGeneratorContainer');
  const customBox = document.getElementById('customTextContainer');
  if (!genBox) return;
  if (customBox) customBox.style.display = 'none';

  const isHidden = genBox.style.display === 'none';
  genBox.style.display = isHidden ? 'block' : 'none';
  if (btn) {
    document.querySelectorAll('.reading-preset-btn').forEach(b => b.classList.remove('active'));
    if (isHidden) btn.classList.add('active');
  }
}

async function handleGenerateReadingText() {
  const btn = document.getElementById('readGenSubmitBtn');
  const cefr = document.getElementById('readGenCefr')?.value || 'B1';
  const fmt = document.getElementById('readGenFormat')?.value || 'text';
  const wordCount = parseInt(document.getElementById('readGenWords')?.value, 10) || 150;
  const topic = document.getElementById('readGenTopic')?.value?.trim() || 'General English';
  const targetRaw = document.getElementById('readGenTarget')?.value?.trim() || '';

  const targetWords = targetRaw
    ? targetRaw.split(/[,;\s]+/).map(w => w.trim()).filter(Boolean)
    : [];

  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Генерация текста (AI)... ⏳';
  }

  try {
    const res = await fetchAPI('/content/generate', {
      method: 'POST',
      body: JSON.stringify({
        cefr_level: cefr,
        topic: topic,
        word_count: wordCount,
        format: fmt,
        target_words: targetWords.length ? targetWords : null
      })
    });

    if (res.ok && res.data) {
      const data = res.data;
      currentReadingText = data.text;
      renderReadingContent(data.text, data.title, data.new_words, data.comprehension_questions);
      showToast('Текст успешно сгенерирован!', 'success');
    } else {
      const err = (res.data && res.data.detail) ? res.data.detail : 'Не удалось сгенерировать текст';
      showToast(typeof err === 'string' ? err : 'Ошибка генерации', 'error');
    }
  } catch (err) {
    showToast('Сетевая ошибка при генерации текста', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Сгенерировать текст (AI) ➔';
    }
  }
}

function loadReadingPreset(presetKey, btn) {
  if (btn) {
    document.querySelectorAll('.reading-preset-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  const customBox = document.getElementById('customTextContainer');
  if (customBox) customBox.style.display = 'none';

  const preset = READING_PRESETS[presetKey] || READING_PRESETS.habits;
  currentReadingText = preset.text;
  renderReadingContent(currentReadingText, preset.title || 'Тематический текст');
}

function toggleCustomTextInput(btn) {
  const customBox = document.getElementById('customTextContainer');
  const genBox = document.getElementById('readingGeneratorContainer');
  if (!customBox) return;
  if (genBox) genBox.style.display = 'none';

  const isHidden = customBox.style.display === 'none';
  customBox.style.display = isHidden ? 'block' : 'none';
  if (btn) {
    document.querySelectorAll('.reading-preset-btn').forEach(b => b.classList.remove('active'));
    if (isHidden) btn.classList.add('active');
  }
  if (isHidden) {
    const input = document.getElementById('customTextInput');
    if (input) input.focus();
  }
}

function applyCustomText() {
  const input = document.getElementById('customTextInput');
  if (!input || !input.value.trim()) return;
  currentReadingText = input.value.trim();
  renderReadingContent(currentReadingText, 'Пользовательский текст');
}

function renderReadingContent(rawText, title = 'Интерактивный материал', newWords = [], questions = []) {
  const container = document.getElementById('readingArticleContent');
  const titleEl = document.getElementById('readingArticleTitle');
  const vocabBox = document.getElementById('readingVocabContainer');
  const compBox = document.getElementById('readingComprehensionContainer');

  if (titleEl) titleEl.textContent = title;
  if (!container) return;
  hideReadingPopover();

  const paragraphs = rawText.split(/\n\s*\n/);
  let html = '';

  paragraphs.forEach(para => {
    const trimmed = para.trim();
    if (!trimmed) return;

    const tokens = trimmed.split(/([a-zA-Z0-9'-]+)/g);
    let paraHtml = '<p style="margin-bottom: var(--space-4);">';

    tokens.forEach(tok => {
      if (/^[a-zA-Z0-9'-]+$/.test(tok)) {
        const cleanTok = tok.toLowerCase();
        const isInDeck = userDeckWordSet.has(cleanTok);
        const deckClass = isInDeck ? ' in-deck' : '';
        paraHtml += `<span class="read-token${deckClass}" onclick="handleReadWordClick(this, '${tok.replace(/'/g, "\\'")}')">${tok}</span>`;
      } else {
        paraHtml += tok.replace(/\n/g, '<br>');
      }
    });

    paraHtml += '</p>';
    html += paraHtml;
  });

  container.innerHTML = html;

  // Render Target/New Vocabulary
  if (vocabBox) {
    if (newWords && newWords.length > 0) {
      vocabBox.style.display = 'block';
      vocabBox.innerHTML = `
        <div style="font-weight: 600; font-size: 1rem; margin-bottom: var(--space-3); color: var(--color-text-primary);">
          Ключевые слова текста (${newWords.length})
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-3);">
          ${newWords.map(w => `
            <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 12px; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <div style="font-weight: 600; font-size: 1rem; color: var(--color-primary);">${w.lemma}</div>
                <div style="font-size: 0.875rem; color: var(--color-text-secondary); margin-top: 2px;">${w.translation_ru}</div>
              </div>
              <button class="btn btn-secondary btn-sm" style="margin-top: 10px; width: 100%;" onclick="addWordToDeck('${w.lemma.replace(/'/g, "\\'")}', '${w.translation_ru.replace(/'/g, "\\'")}', 'B1', this)">
                + В колоду
              </button>
            </div>
          `).join('')}
        </div>
      `;
    } else {
      vocabBox.style.display = 'none';
      vocabBox.innerHTML = '';
    }
  }

  // Render Comprehension Questions
  if (compBox) {
    if (questions && questions.length > 0) {
      compBox.style.display = 'block';
      compBox.innerHTML = `
        <div style="font-weight: 600; font-size: 1.0625rem; margin-bottom: var(--space-4); display: flex; align-items: center; justify-content: space-between;">
          <span>Вопросы на понимание прочитанного (${questions.length})</span>
          <span style="font-size: 0.8125rem; color: var(--color-text-secondary); font-weight: normal;">Выберите правильный ответ</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: var(--space-4);">
          ${questions.map((q, idx) => `
            <div style="background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 16px;">
              <div style="font-weight: 500; font-size: 0.9375rem; margin-bottom: 12px; color: var(--color-text-primary);">
                ${idx + 1}. ${q.q}
              </div>
              <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px;">
                ${q.options.map(opt => `
                  <button class="btn btn-secondary btn-sm comp-opt-btn" style="text-align: left; padding: 8px 12px; white-space: normal; height: auto;" onclick="handleComprehensionOption(this, ${opt === q.answer}, '${q.answer.replace(/'/g, "\\'")}')">
                    ${opt}
                  </button>
                `).join('')}
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } else {
      compBox.style.display = 'none';
      compBox.innerHTML = '';
    }
  }
}

function handleComprehensionOption(btn, isCorrect, correctAns) {
  const parent = btn.parentElement;
  if (!parent) return;

  parent.querySelectorAll('.comp-opt-btn').forEach(b => {
    b.disabled = true;
    if (b.textContent.trim() === correctAns.trim()) {
      b.style.backgroundColor = 'var(--color-success-bg)';
      b.style.borderColor = 'var(--color-success-border)';
      b.style.color = 'var(--color-success)';
      b.innerHTML += ' ✓';
    }
  });

  if (!isCorrect) {
    btn.style.backgroundColor = 'var(--color-danger-bg)';
    btn.style.borderColor = 'var(--color-danger-border)';
    btn.style.color = 'var(--color-danger)';
    btn.innerHTML += ' ✗';
    showToast('Неверно. Правильный ответ подсвечен зеленым.', 'error');
  } else {
    showToast('Верно! Отличный результат.', 'success');
  }
}

async function handleReadWordClick(element, rawWord) {
  const cleanWord = rawWord.toLowerCase().replace(/[^a-z'-]/g, '');
  if (!cleanWord) return;

  hideReadingPopover();
  currentActiveToken = element;
  element.classList.add('active-token');

  const popover = document.getElementById('readingWordPopover');
  const wordEl = document.getElementById('popoverWord');
  const cefrEl = document.getElementById('popoverCefr');
  const transEl = document.getElementById('popoverTrans');
  const addBtn = document.getElementById('popoverAddBtn');
  const speakBtn = document.getElementById('popoverSpeakBtn');

  if (!popover || !wordEl || !transEl) return;

  wordEl.textContent = cleanWord;
  let quick = QUICK_DICT[cleanWord] || QUICK_DICT[cleanWord.replace(/s$/, '')] || QUICK_DICT[cleanWord.replace(/ed$/, '')] || QUICK_DICT[cleanWord.replace(/ing$/, '')];
  let trans = quick ? quick.ru : 'Перевод...';
  let cefr = quick ? quick.cefr : (cleanWord.length > 8 ? 'B2' : (cleanWord.length > 5 ? 'B1' : 'A2'));

  cefrEl.textContent = cefr;
  transEl.textContent = trans;

  addBtn.disabled = false;
  addBtn.textContent = 'В колоду FSRS ✓';
  addBtn.onclick = () => addWordToDeck(cleanWord, transEl.textContent, cefrEl.textContent, addBtn);
  speakBtn.onclick = () => speakWord(cleanWord);

  popover.style.display = 'block';
  const rect = element.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();

  let top = rect.bottom + 8;
  let left = rect.left + (rect.width / 2) - (popoverRect.width / 2);

  if (left < 16) left = 16;
  if (left + popoverRect.width > window.innerWidth - 16) {
    left = window.innerWidth - popoverRect.width - 16;
  }
  if (top + popoverRect.height > window.innerHeight - 16) {
    top = rect.top - popoverRect.height - 8;
  }

  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;

  if (!quick) {
    try {
      const res = await fetchAPI('/words/analyze', {
        method: 'POST',
        body: JSON.stringify({ sentence: `I would like to learn about ${cleanWord}.` })
      });
      if (res.ok && res.data && res.data.extracted_words) {
        const found = res.data.extracted_words.find(w => (w.lemma || '').toLowerCase() === cleanWord || (w.text || '').toLowerCase() === cleanWord);
        if (found) {
          transEl.textContent = found.translation_ru || cleanWord;
          cefrEl.textContent = found.cefr_level || cefr;
        } else {
          transEl.textContent = `Слово: ${cleanWord}`;
        }
      } else {
        transEl.textContent = `Слово: ${cleanWord}`;
      }
    } catch (err) {
      transEl.textContent = `Слово: ${cleanWord}`;
    }
  }
}

// ==========================================
// 7. PRACTICE STUDIO (/app/practice)
// ==========================================
let currentPracticeTab = 'writing';
let currentSpeakingScenario = null;
let speakingChatHistoryData = [];
let speakingScenarios = [];

function switchPracticeTab(tab) {
  currentPracticeTab = tab;
  const writingSec = document.getElementById('practiceWritingSection');
  const speakingSec = document.getElementById('practiceSpeakingSection');
  const writingBtn = document.getElementById('practiceTabWritingBtn');
  const speakingBtn = document.getElementById('practiceTabSpeakingBtn');

  if (tab === 'speaking') {
    if (writingSec) writingSec.style.display = 'none';
    if (speakingSec) speakingSec.style.display = 'block';
    if (writingBtn) writingBtn.classList.remove('active');
    if (speakingBtn) speakingBtn.classList.add('active');
    loadSpeakingScenarios();
  } else {
    if (writingSec) writingSec.style.display = 'block';
    if (speakingSec) speakingSec.style.display = 'none';
    if (writingBtn) writingBtn.classList.add('active');
    if (speakingBtn) speakingBtn.classList.remove('active');
  }
}

function loadPractice() {
  switchPracticeTab(currentPracticeTab || 'writing');
}

async function handleWritingSubmit() {
  const input = document.getElementById('writingTextInput');
  const btn = document.getElementById('writingSubmitBtn');

  if (!input || !input.value.trim()) {
    alert('Пожалуйста, введите текст для проверки.');
    return;
  }

  const text = input.value.trim();
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Анализ текста AI...';
  }

  try {
    const res = await fetchAPI('/practice/writing/review', {
      method: 'POST',
      body: JSON.stringify({ text })
    });

    if (res.ok && res.data) {
      renderWritingResults(res.data);
    } else {
      let msg = res.data && res.data.detail ? res.data.detail : 'Ошибка при анализе текста';
      alert('Ошибка: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)));
    }
  } catch (err) {
    alert('Сетевая ошибка при анализе текста');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Проверить текст ➔';
    }
  }
}

function renderWritingResults(data) {
  const container = document.getElementById('writingResultsContainer');
  if (!container) return;
  container.style.display = 'block';

  let correctionsHtml = '';
  if (data.corrections && data.corrections.length > 0) {
    correctionsHtml = `
      <div style="margin-bottom: var(--space-4);">
        <h4 style="font-size: 0.9375rem; font-weight: 600; margin-bottom: var(--space-2); color: var(--color-danger);">Найденные неточности и исправления:</h4>
        <div style="display: flex; flex-direction: column; gap: var(--space-2);">
          ${data.corrections.map(c => `
            <div style="padding: 10px 14px; background: var(--color-surface-subtle); border-left: 3px solid var(--color-danger); border-radius: var(--radius-sm); font-size: 0.875rem;">
              <div style="display: flex; gap: 8px; align-items: baseline; margin-bottom: 2px;">
                <span style="text-decoration: line-through; color: var(--color-text-muted);">${c.original}</span>
                <span>→</span>
                <strong style="color: var(--color-success);">${c.improved}</strong>
              </div>
              <div style="color: var(--color-text-secondary); font-size: 0.8125rem;">${c.explanation}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  } else {
    correctionsHtml = `
      <div style="padding: 12px 16px; background: var(--color-success-bg); border: 1px solid var(--color-success-border); border-radius: var(--radius-md); font-size: 0.875rem; color: var(--color-success); margin-bottom: var(--space-4);">
        ✓ Серьезных грамматических ошибок не обнаружено. Текст чистый и связный.
      </div>
    `;
  }

  let betterPhrasingsHtml = '';
  if (data.better_phrasings && data.better_phrasings.length > 0) {
    betterPhrasingsHtml = `
      <div style="margin-bottom: var(--space-4);">
        <h4 style="font-size: 0.9375rem; font-weight: 600; margin-bottom: var(--space-2);">Как сказал бы носитель языка:</h4>
        <ul style="padding-left: 20px; font-size: 0.875rem; color: var(--color-text-secondary); display: flex; flex-direction: column; gap: 4px;">
          ${data.better_phrasings.map(p => `<li><em>"${p}"</em></li>`).join('')}
        </ul>
      </div>
    `;
  }

  let vocabHtml = '';
  if (data.useful_vocab && data.useful_vocab.length > 0) {
    vocabHtml = `
      <div>
        <h4 style="font-size: 0.9375rem; font-weight: 600; margin-bottom: var(--space-2);">Рекомендуемые слова в колоду:</h4>
        <div style="display: flex; gap: var(--space-2); flex-wrap: wrap;">
          ${data.useful_vocab.map(v => `
            <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-full); font-size: 0.8125rem;">
              <strong>${v.lemma}</strong>
              <span style="color: var(--color-text-secondary);">${v.translation_ru}</span>
              <button class="btn btn-primary btn-sm" style="padding: 2px 8px; font-size: 0.75rem; height: 24px;" onclick="addWordToDeck('${v.lemma.replace(/'/g, "\\'")}', '${v.translation_ru.replace(/'/g, "\\'")}', 'B2', this)">+ Колода</button>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div style="padding: var(--space-5); background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg);">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: var(--space-3); margin-bottom: var(--space-4); border-bottom: 1px solid var(--color-border); padding-bottom: var(--space-3);">
        <div>
          <span style="font-size: 0.8125rem; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Оценка текста</span>
          <div style="display: flex; align-items: baseline; gap: 8px;">
            <span style="font-size: 2rem; font-weight: 700; color: var(--color-text-primary);">${data.score}</span>
            <span style="font-size: 1rem; color: var(--color-text-muted);">/ 100</span>
          </div>
        </div>
        <div style="text-align: right;">
          <span style="font-size: 0.8125rem; color: var(--color-text-muted);">Примерный уровень</span>
          <div><span class="cefr-pill" style="font-size: 0.9375rem; padding: 4px 10px;">${data.cefr_estimate || 'B2'}</span></div>
        </div>
      </div>

      <div style="font-size: 0.9375rem; color: var(--color-text-primary); margin-bottom: var(--space-4); font-weight: 500;">
        ${data.summary_ru}
      </div>

      ${correctionsHtml}
      ${betterPhrasingsHtml}
      ${vocabHtml}
    </div>
  `;

  container.scrollIntoView({ behavior: 'smooth' });
}

async function loadSpeakingScenarios() {
  const container = document.getElementById('speakingScenariosList');
  if (!container) return;

  if (speakingScenarios.length === 0) {
    try {
      const res = await fetchAPI('/practice/scenarios');
      if (res.ok && res.data) {
        speakingScenarios = res.data;
      }
    } catch (err) {
      console.warn('Failed to load scenarios:', err);
    }
  }

  if (speakingScenarios.length === 0) return;

  container.innerHTML = speakingScenarios.map(sc => `
    <div class="scenario-card ${currentSpeakingScenario && currentSpeakingScenario.id === sc.id ? 'active' : ''}" 
         onclick="selectSpeakingScenario('${sc.id}')"
         style="cursor: pointer; padding: 14px 16px; background: var(--color-surface); border: 1px solid ${currentSpeakingScenario && currentSpeakingScenario.id === sc.id ? 'var(--color-primary)' : 'var(--color-border)'}; border-radius: var(--radius-md); transition: var(--transition);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="font-size: 1.5rem;">${sc.icon || '💬'}</span>
        <span class="cefr-pill">${sc.level || 'B1'}</span>
      </div>
      <strong style="display: block; font-size: 0.9375rem; margin-bottom: 4px;">${sc.title}</strong>
    </div>
  `).join('');

  if (!currentSpeakingScenario && speakingScenarios.length > 0) {
    selectSpeakingScenario(speakingScenarios[0].id);
  }
}

function selectSpeakingScenario(scenarioId) {
  const scenario = speakingScenarios.find(s => s.id === scenarioId);
  if (!scenario) return;
  currentSpeakingScenario = scenario;
  speakingChatHistoryData = [];

  document.querySelectorAll('.scenario-card').forEach(el => {
    el.style.borderColor = 'var(--color-border)';
  });

  const chat = document.getElementById('speakingChatHistory');
  if (chat) {
    chat.innerHTML = '';
    appendSpeakingChatMessage('ai', scenario.prompt);
  }
}

function appendSpeakingChatMessage(role, text, feedback, suggestion) {
  const chat = document.getElementById('speakingChatHistory');
  if (!chat) return;

  speakingChatHistoryData.push({ role, content: text });

  const isAi = role === 'ai';
  const msgEl = document.createElement('div');
  msgEl.style.display = 'flex';
  msgEl.style.flexDirection = 'column';
  msgEl.style.alignItems = isAi ? 'flex-start' : 'flex-end';
  msgEl.style.gap = '4px';

  let feedbackSnippet = '';
  if (feedback || suggestion) {
    feedbackSnippet = `
      <div style="font-size: 0.75rem; color: var(--color-text-muted); background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-sm); padding: 4px 8px; margin-top: 4px; max-width: 320px;">
        ${feedback ? `<div>💡 ${feedback}</div>` : ''}
        ${suggestion ? `<div style="font-style: italic;">${suggestion}</div>` : ''}
      </div>
    `;
  }

  msgEl.innerHTML = `
    <div style="display: flex; align-items: center; gap: 6px; flex-direction: ${isAi ? 'row' : 'row-reverse'}; max-width: 80%;">
      <div style="padding: 10px 16px; border-radius: ${isAi ? '16px 16px 16px 4px' : '16px 16px 4px 16px'}; background: ${isAi ? 'var(--color-surface-subtle)' : 'var(--color-primary)'}; color: ${isAi ? 'var(--color-text-primary)' : 'var(--color-text-inverted)'}; font-size: 0.9375rem; line-height: 1.5;">
        ${text}
      </div>
      ${isAi ? `<button onclick="speakWord('${text.replace(/'/g, "\\'")}')" style="background: none; border: none; cursor: pointer; color: var(--color-text-muted); font-size: 1rem;" title="Озвучить ответ">🔊</button>` : ''}
    </div>
    ${feedbackSnippet}
  `;

  chat.appendChild(msgEl);
  chat.scrollTop = chat.scrollHeight;

  if (isAi && speakingChatHistoryData.length > 1) {
    speakWord(text);
  }
}

async function handleSendSpeakingMessage() {
  const input = document.getElementById('speakingUserInput');
  const btn = document.getElementById('speakingSendBtn');
  if (!input || !input.value.trim() || !currentSpeakingScenario) return;

  const userText = input.value.trim();
  input.value = '';

  appendSpeakingChatMessage('user', userText);

  if (btn) {
    btn.disabled = true;
    btn.textContent = '...';
  }

  try {
    const res = await fetchAPI('/practice/speaking/respond', {
      method: 'POST',
      body: JSON.stringify({
        scenario: currentSpeakingScenario.id,
        user_message: userText,
        history: speakingChatHistoryData.slice(-6)
      })
    });

    if (res.ok && res.data) {
      appendSpeakingChatMessage('ai', res.data.ai_message, res.data.feedback_ru, res.data.suggested_phrasing);
    } else {
      appendSpeakingChatMessage('ai', "I hear you! That's an interesting thought. Could you tell me more?");
    }
  } catch (err) {
    appendSpeakingChatMessage('ai', "I understand. Let's keep practicing!");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Отправить';
    }
  }
}

// ==========================================
// 8. MISTAKES JOURNAL (/app/mistakes)
// ==========================================
let mistakeSourceFilter = 'ALL';

async function loadMistakes() {
  const container = document.getElementById('mistakesListContainer');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--color-text-muted); text-align: center; padding: 40px 0;">Загрузка журнала ошибок...</div>';

  let url = '/mistakes?limit=50';
  if (mistakeSourceFilter && mistakeSourceFilter !== 'ALL') {
    url += `&source=${mistakeSourceFilter}`;
  }

  const res = await fetchAPI(url);
  if (!res.ok || !Array.isArray(res.data) || res.data.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">✓</div>
        <h3 class="empty-title">Журнал ошибок пуст</h3>
        <p class="empty-desc">Здесь будут сохраняться неточности из проверки письма, квизов и повторения слов для дальнейшей отработки.</p>
      </div>
    `;
    return;
  }

  const sourceLabels = {
    writing: 'Письмо',
    quiz: 'Квиз',
    review: 'Повторение',
    tutor: 'Репетитор'
  };

  container.innerHTML = res.data.map(m => {
    const sLabel = sourceLabels[m.source] || m.source;
    const dateStr = m.created_at ? new Date(m.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) : '';
    const hasCardBtn = m.has_card
      ? '<span style="color: var(--color-success); font-size: 0.8125rem; font-weight: 500;">Карточка создана ✓</span>'
      : `<button class="btn btn-secondary btn-sm" onclick="convertMistakeToCard(${m.id}, this)">Сделать карточкой (Cloze) →</button>`;

    return `
      <div style="padding: 16px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); display: flex; flex-direction: column; gap: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; gap: 8px; align-items: center;">
            <span class="cefr-pill" style="font-size: 0.75rem;">${sLabel}</span>
            <span style="font-size: 0.75rem; color: var(--color-text-muted);">${dateStr}</span>
          </div>
          <div>${hasCardBtn}</div>
        </div>
        <div style="display: flex; gap: 10px; align-items: baseline; font-size: 0.9375rem; flex-wrap: wrap;">
          <span style="color: var(--color-danger); text-decoration: line-through;">${m.original}</span>
          <span>→</span>
          <strong style="color: var(--color-success);">${m.correction}</strong>
        </div>
        ${m.explanation ? `<div style="font-size: 0.8125rem; color: var(--color-text-secondary);">${m.explanation}</div>` : ''}
      </div>
    `;
  }).join('');
}

function setMistakeFilter(source, btn) {
  mistakeSourceFilter = source;
  document.querySelectorAll('.mistake-filter-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-source') === source);
  });
  loadMistakes();
}

async function convertMistakeToCard(mistakeId, btn) {
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Создание...';
  }
  const res = await fetchAPI(`/mistakes/${mistakeId}/to-cards`, { method: 'POST' });
  if (res.ok) {
    showToast('Карточка с пропуском успешно создана!', 'success');
    if (btn) {
      btn.outerHTML = '<span style="color: var(--color-success); font-size: 0.8125rem; font-weight: 500;">Карточка создана ✓</span>';
    }
  } else {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Сделать карточкой (Cloze) →';
    }
    showToast('Не удалось создать карточку: ' + (res.data ? res.data.detail : 'Ошибка'), 'error');
  }
}

// ==========================================
// 8. AI TUTOR (/app/tutor)
// ==========================================
let tutorHistory = [];
let isTutorSending = false;

function loadTutor() {
  const container = document.getElementById('tutorMessagesContainer');
  if (!container) return;

  if (tutorHistory.length === 0) {
    container.innerHTML = `
      <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 16px; max-width: 80%; align-self: flex-start;">
        <div style="font-weight: 600; color: var(--color-primary); margin-bottom: 6px;">AI-Репетитор 🎓</div>
        <div style="font-size: 0.9375rem; line-height: 1.6; color: var(--color-text-primary);">
          Здравствуйте! Я ваш персональный наставник по английскому языку. Я отслеживаю ваш текущий уровень, слова на изучении и типичные ошибки из тренировок.<br><br>
          Спросите меня о значении любого слова, попросите проверить грамматику предложения или составить персональный квиз!
        </div>
      </div>
    `;
  }
}

function handleTutorQuickAction(action) {
  const input = document.getElementById('tutorInput');
  if (!input) return;

  if (action === 'explain') {
    input.value = 'Объясни значение и оттенки слова ';
    input.focus();
  } else if (action === 'check') {
    input.value = 'Проверь предложение: ';
    input.focus();
  } else if (action === 'quiz') {
    input.value = 'Сделай мини-квиз по моим словам из колоды';
    handleTutorSubmit();
  } else if (action === 'mistakes') {
    input.value = 'Какие ошибки я чаще всего допускаю и как их избежать?';
    handleTutorSubmit();
  }
}

async function handleTutorSubmit(e) {
  if (e && e.preventDefault) e.preventDefault();
  if (isTutorSending) return;

  const input = document.getElementById('tutorInput');
  const container = document.getElementById('tutorMessagesContainer');
  const sendBtn = document.getElementById('tutorSendBtn');
  const limitEl = document.getElementById('tutorLimitRemaining');
  if (!input || !container) return;

  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  isTutorSending = true;
  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.textContent = 'Думает...';
  }

  // Append user message
  const userBubble = document.createElement('div');
  userBubble.style.cssText = 'background: var(--color-primary); color: var(--color-text-inverted); border-radius: var(--radius-md); padding: 12px 16px; max-width: 80%; align-self: flex-end; font-size: 0.9375rem; word-break: break-word;';
  userBubble.textContent = msg;
  container.appendChild(userBubble);

  // Append loading indicator
  const loadingBubble = document.createElement('div');
  loadingBubble.id = 'tutorLoadingBubble';
  loadingBubble.style.cssText = 'background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 12px 16px; max-width: 80%; align-self: flex-start; font-size: 0.875rem; color: var(--color-text-muted);';
  loadingBubble.textContent = 'Репетитор анализирует вопрос... ⏳';
  container.appendChild(loadingBubble);
  container.scrollTop = container.scrollHeight;

  try {
    const res = await fetchAPI('/tutor/chat', {
      method: 'POST',
      body: JSON.stringify({
        message: msg,
        history: tutorHistory.slice(-6)
      })
    });

    if (loadingBubble.parentNode) {
      loadingBubble.parentNode.removeChild(loadingBubble);
    }

    if (res.ok && res.data) {
      const data = res.data;
      if (limitEl && typeof data.daily_requests_remaining === 'number') {
        limitEl.textContent = data.daily_requests_remaining;
      }

      tutorHistory.push({ role: 'user', content: msg });
      tutorHistory.push({ role: 'assistant', content: data.reply });

      const assistantBubble = document.createElement('div');
      assistantBubble.style.cssText = 'background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 16px; max-width: 85%; align-self: flex-start; font-size: 0.9375rem; line-height: 1.6; word-break: break-word;';

      let replyHtml = data.reply
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');

      if (data.tool_calls_executed && data.tool_calls_executed.length > 0) {
        const toolsNames = data.tool_calls_executed.map(t => t.tool_name).join(', ');
        replyHtml += `<div style="margin-top: 10px; font-size: 0.75rem; color: var(--color-text-muted); border-top: 1px solid var(--color-border); padding-top: 6px;">🛠 Использованы инструменты: ${toolsNames}</div>`;
      }

      assistantBubble.innerHTML = `
        <div style="font-weight: 600; color: var(--color-primary); margin-bottom: 6px;">AI-Репетитор 🎓</div>
        <div>${replyHtml}</div>
      `;
      container.appendChild(assistantBubble);
      container.scrollTop = container.scrollHeight;
    } else {
      const errDetail = res.data ? (res.data.detail || JSON.stringify(res.data)) : 'Ошибка соединения';
      showToast(typeof errDetail === 'string' ? errDetail : 'Ошибка ответа репетитора', 'error');
    }
  } catch (err) {
    if (loadingBubble.parentNode) {
      loadingBubble.parentNode.removeChild(loadingBubble);
    }
    showToast('Сетевая ошибка при связи с репетитором', 'error');
  } finally {
    isTutorSending = false;
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Отправить ➔';
    }
    if (input) input.focus();
  }
}

// Entrypoint initialization
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('appRoot')) {
      renderRoute();
    }
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createStudyQueueManager };
}
