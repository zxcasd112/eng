// ENG TUTOR Web Client — Grey Zinc Minimalist Architecture

const API_BASE = '/api/v1';

// Global App State
let currentUser = null;
let currentRoute = '/app';

// Study Session State
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

// Audio Pronunciation via Web Speech API
function speakWord(text) {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 0.92;
    window.speechSynthesis.speak(utterance);
  }
}

// Unified API Fetch with Cookie Authentication
async function fetchAPI(endpoint, options = {}) {
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

  return { ok: res.ok, status: res.status, data };
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
      badge.textContent = currentUser.username ? '@' + currentUser.username : 'TG: ' + currentUser.telegram_id;
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

window.addEventListener('popstate', renderRoute);

async function renderRoute() {
  const path = window.location.pathname.replace(/\/$/, '') || '/app';
  currentRoute = path;

  // Views references
  const loadingView = document.getElementById('loadingView');
  const loginView = document.getElementById('loginView');
  const dashboardView = document.getElementById('dashboardView');
  const studyView = document.getElementById('studyView');
  const wordsView = document.getElementById('wordsView');
  const analyticsView = document.getElementById('analyticsView');
  const profileView = document.getElementById('profileView');

  // Hide all views first
  [loadingView, loginView, dashboardView, studyView, wordsView, analyticsView, profileView].forEach(v => {
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

// Telegram Login Widget Loader
async function initTelegramLoginWidget() {
  const container = document.getElementById('telegramLoginWidgetContainer');
  if (!container || container.dataset.loaded) return;
  container.dataset.loaded = 'true';

  let botUsername = 'ENG_Tutor_FSRS_bot';
  try {
    const res = await fetchAPI('/auth/widget-config');
    if (res.ok && res.data && res.data.bot_username) {
      botUsername = res.data.bot_username;
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
}

// Callback for Telegram Login Widget
window.onTelegramAuth = async function(user) {
  const res = await fetchAPI('/auth/telegram', {
    method: 'POST',
    body: JSON.stringify(user)
  });
  if (res.ok) {
    currentUser = res.data.user;
    updateUserUI();
    navigate('/app');
  } else {
    alert('Ошибка авторизации Telegram Widget: ' + (res.data ? res.data.detail : 'Попробуйте снова'));
  }
};

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
    const [dueRes, profRes, anRes] = await Promise.all([
      fetchAPI('/cards/due?limit=50'),
      fetchAPI('/profile'),
      fetchAPI('/profile/analytics')
    ]);

    // Due Today
    const dueCount = dueRes.ok && Array.isArray(dueRes.data) ? dueRes.data.length : 0;
    const dueEl = document.getElementById('dashDueCount');
    if (dueEl) dueEl.textContent = dueCount;

    // Daily Goal & Streak
    if (profRes.ok && profRes.data) {
      const goal = profRes.data.daily_goal || 15;
      const streak = profRes.data.current_streak || 0;
      
      const streakBadge = document.getElementById('streakBadge');
      if (streakBadge) {
        streakBadge.style.display = 'inline-flex';
        streakBadge.textContent = `🔥 ${streak} дн`;
      }
      const dashStreak = document.getElementById('dashStreak');
      if (dashStreak) dashStreak.textContent = `${streak} дн`;

      const goalProgress = document.getElementById('dashGoalProgress');
      const goalBar = document.getElementById('dashGoalBar');
      const reviewedToday = Math.min(goal, Math.max(0, goal - dueCount));
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

  container.innerHTML = res.data.map(rec => `
    <div class="word-card">
      <div>
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <div class="word-lemma">${rec.lemma}</div>
          <span class="cefr-pill">${rec.cefr_level || 'B1'}</span>
        </div>
        <div class="word-trans">${rec.translation_ru}</div>
        <div style="font-size: 0.8125rem; color: var(--color-text-muted); margin-top: 8px;">
          ${rec.reason || 'Оптимально для вашего словарного запаса'}
        </div>
      </div>
      <div style="margin-top: 16px; display: flex; gap: 8px;">
        <button class="btn btn-primary btn-sm" style="flex: 1;" onclick="addWordToDeck('${rec.lemma.replace(/'/g, "\\'")}', '${rec.translation_ru.replace(/'/g, "\\'")}', '${rec.cefr_level}', this)">
          В колоду
        </button>
        <button class="btn btn-secondary btn-sm" onclick="speakWord('${rec.lemma.replace(/'/g, "\\'")}')" aria-label="Озвучить слово">
          🔊
        </button>
      </div>
    </div>
  `).join('');
}

async function addWordToDeck(lemma, translation, cefr, btn) {
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Добавление...';
  }

  const res = await fetchAPI('/words', {
    method: 'POST',
    body: JSON.stringify({
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
  } else {
    alert('Не удалось добавить слово: ' + (res.data ? res.data.detail : 'Ошибка'));
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

  if (!res.ok || !res.data || !res.data.words || res.data.words.length === 0) {
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
        <button class="btn btn-secondary" style="height: auto; padding: 12px 16px; text-align: left; justify-content: flex-start; white-space: normal;" onclick="submitQuizAnswer('${opt.replace(/'/g, "\\'")}', this)">
          ${opt}
        </button>
      `).join('')}
    </div>
    <div id="quizFeedbackContainer" style="margin-top: 16px;"></div>
  `;
}

async function submitQuizAnswer(chosenOption, btn) {
  if (!currentQuiz) return;

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
    if (isCorrect) {
      btn.style.borderColor = 'var(--color-success)';
      btn.style.background = 'var(--color-success-bg)';
      btn.style.color = 'var(--color-success)';
    } else {
      btn.style.borderColor = 'var(--color-danger)';
      btn.style.background = 'var(--color-danger-bg)';
      btn.style.color = 'var(--color-danger)';
    }

    if (feedback) {
      feedback.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-radius: var(--radius-md); background: ${isCorrect ? 'var(--color-success-bg)' : 'var(--color-danger-bg)'}; border: 1px solid ${isCorrect ? 'var(--color-success-border)' : 'var(--color-danger-border)'};">
          <span style="font-size: 0.875rem; color: ${isCorrect ? 'var(--color-success)' : 'var(--color-danger)'};">
            ${isCorrect ? 'Верно!' : `Правильный ответ: <strong>${res.data.correct_answer}</strong>`}
          </span>
          <button class="btn btn-primary btn-sm" onclick="loadInteractiveQuiz()">Следующий ➔</button>
        </div>
      `;
    }
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
            <a href="https://t.me/ENG_Tutor_FSRS_bot" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm">Открыть Telegram-бота ➔</a>
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

  studyQueue = res.data;
  studyIndex = 0;
  isAnswerRevealed = false;
  renderCurrentStudyCard();
}

function setStudyTypeFilter(type) {
  studyTypeFilter = type;
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
  isAnswerRevealed = true;
  const backFace = document.getElementById('cardBackFace');
  const revealBtn = document.getElementById('revealBtnContainer');
  if (backFace) backFace.style.display = 'block';
  if (revealBtn) revealBtn.style.display = 'none';
}

async function submitCardRating(cardId, rating) {
  await fetchAPI(`/cards/${cardId}/review`, {
    method: 'POST',
    body: JSON.stringify({ rating: rating })
  });

  studyIndex++;
  isAnswerRevealed = false;
  renderCurrentStudyCard();
}

// Global hotkeys for study studio
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
  if (cardTypesContainer && an.card_type_accuracy) {
    const types = [
      { key: 'en_ru', label: 'Прямой перевод (EN ➔ RU)' },
      { key: 'ru_en', label: 'Активное воспроизведение (RU ➔ EN)' },
      { key: 'cloze', label: 'Пропуск в контексте (Cloze)' },
      { key: 'audio', label: 'Восприятие на слух (Audio)' }
    ];
    cardTypesContainer.innerHTML = types.map(t => {
      const acc = an.card_type_accuracy[t.key] !== undefined ? an.card_type_accuracy[t.key] : 100;
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
  if (forecastContainer && an.forecast_7d) {
    const maxVal = Math.max(1, ...an.forecast_7d.map(d => d.due_count));
    forecastContainer.innerHTML = an.forecast_7d.map(d => {
      const heightPct = Math.round((d.due_count / maxVal) * 100);
      const dayLabel = d.date.slice(5);
      return `
        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; justify-content: flex-end;">
          <div style="font-size: 0.75rem; font-weight: 600; color: var(--color-text-muted);">${d.due_count}</div>
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
    container.innerHTML = '<div style="color: var(--color-text-muted);">Недостаточно данных для графика.</div>';
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
    const x = padLeft + (idx / Math.max(1, dailyData.length - 1)) * chartW;
    const rate = d.retention_rate !== null ? d.retention_rate : 100;
    const y = padTop + chartH - (rate / 100) * chartH;
    return { x, y, rate, date: d.date };
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

// Entrypoint initialization
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('appRoot')) {
    renderRoute();
  }
});
