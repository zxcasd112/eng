// ENG TUTOR Web Client — Spaced Repetition Cabinet & Learning Studio

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
    utterance.rate = 0.9;
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
      badge.textContent = `{ ${currentUser.username ? '@' + currentUser.username : 'TG: ' + currentUser.telegram_id} } _`;
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
  document.querySelectorAll('.nav-link-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-route') === currentPath);
  });
  document.querySelectorAll('.subnav-pill').forEach(btn => {
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
    alert('Ошибка аутентификации Telegram Widget');
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
  // Parallel fetch: stats & due cards, profile, recommendations
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
      if (dashStreak) dashStreak.textContent = `${streak} 🔥`;

      const goalProgress = document.getElementById('dashGoalProgress');
      const goalBar = document.getElementById('dashGoalBar');
      // Calculate reviewed today from analytics if present
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

    // Load recommendations
    loadDashboardRecommendations();
    // Load quiz lab question
    loadInteractiveQuiz();
  } catch (err) {
    console.error('Error loading dashboard:', err);
  }
}

async function loadDashboardRecommendations() {
  const container = document.getElementById('dashRecommendationsGrid');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--pewter-text); padding: 20px;">Подбираем рекомендации по методике Krashen i+1...</div>';

  const res = await fetchAPI('/profile/recommendations?limit=5');
  if (!res.ok || !Array.isArray(res.data) || res.data.length === 0) {
    container.innerHTML = '<div style="color: var(--pewter-text); padding: 20px;">Все текущие рекомендации изучены. Добавь новые тексты или слова!</div>';
    return;
  }

  container.innerHTML = res.data.map(rec => `
    <div class="word-card" style="display: flex; flex-direction: column; justify-content: space-between;">
      <div>
        <div class="word-card-top">
          <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <div class="word-card-lemma">${rec.lemma}</div>
            <span class="pill-tag" style="color: var(--nest-crimson);">${rec.cefr_level || 'B1'}</span>
          </div>
          <div class="word-card-trans">${rec.translation_ru}</div>
        </div>
        <div style="font-size: 11px; color: var(--pewter-text); margin: 8px 0;">
          💡 ${rec.reason || 'Оптимально для твоего уровня лексики'}
        </div>
      </div>
      <div style="margin-top: 14px; display: flex; gap: 8px;">
        <button class="btn-primary" style="flex: 1; height: 36px; font-size: 12px;" onclick="addWordToDeck('${rec.lemma.replace(/'/g, "\\'")}', '${rec.translation_ru.replace(/'/g, "\\'")}', '${rec.cefr_level}', this)">
          ➕ В колоду
        </button>
        <button class="btn-secondary" style="height: 36px; padding: 0 12px;" onclick="speakWord('${rec.lemma.replace(/'/g, "\\'")}')">
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
      btn.style.background = 'var(--emerald-success)';
      btn.style.borderColor = 'var(--emerald-success)';
    }
  } else {
    alert('Не удалось добавить слово: ' + (res.data ? res.data.detail : 'Ошибка'));
    if (btn) {
      btn.disabled = false;
      btn.textContent = '➕ В колоду';
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
    container.innerHTML = '<div style="color: var(--pewter-text); font-size: 12px;">Введи полное предложение на английском.</div>';
    return;
  }

  container.innerHTML = '<div style="color: var(--pewter-text); font-size: 13px; padding: 12px 0;">⏳ Анализируем текст и извлекаем лексику...</div>';

  const res = await fetchAPI('/sentences', {
    method: 'POST',
    body: JSON.stringify({ sentence: text })
  });

  if (!res.ok || !res.data || !res.data.words || res.data.words.length === 0) {
    container.innerHTML = `
      <div style="background: var(--carbon-panel); border: 1px solid var(--smoke-outline); border-radius: 14px; padding: 16px;">
        <div style="color: var(--pewter-text);">Новых неизвестных слов в предложении не найдено или они уже есть в колоде.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="margin-top: 12px;">
      <div style="font-size: 12px; color: var(--emerald-success); margin-bottom: 10px;">
        ✅ ИЗВЛЕЧЕНЫ СЛОВА И КОНСТРУКЦИИ ДЛЯ ИЗУЧЕНИЯ (${res.data.words.length}):
      </div>
      <div style="display: flex; flex-direction: column; gap: 8px;">
        ${res.data.words.map(w => `
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--carbon-panel); border: 1px solid var(--smoke-outline); border-radius: 12px;">
            <div>
              <strong style="font-family: var(--font-display); font-size: 15px;">${w.lemma}</strong>
              <span class="pill-tag" style="margin-left: 8px; color: var(--nest-crimson);">${w.cefr_level || 'B2'}</span>
              <span style="color: var(--pewter-text); margin-left: 8px;">— ${w.translation_ru}</span>
              ${w.context_sentence ? `<div style="font-size: 11px; color: var(--pewter-text); margin-top: 4px;">💬 "${w.context_sentence}"</div>` : ''}
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn-primary" style="height: 34px; padding: 0 14px; font-size: 12px;" onclick="addWordToDeck('${w.lemma.replace(/'/g, "\\'")}', '${w.translation_ru.replace(/'/g, "\\'")}', '${w.cefr_level}', this)">
                ➕ В колоду
              </button>
              <button class="btn-secondary" style="height: 34px; padding: 0 10px;" onclick="speakWord('${w.lemma.replace(/'/g, "\\'")}')">
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

  container.innerHTML = '<div style="color: var(--pewter-text); text-align: center; padding: 30px;">Загружаем вопрос квиза...</div>';

  const res = await fetchAPI('/quiz/multiple-choice');
  if (!res.ok || !res.data) {
    container.innerHTML = '<div style="color: var(--pewter-text); text-align: center; padding: 24px;">Для квиза нужно добавить хотя бы несколько слов в колоду.</div>';
    return;
  }

  currentQuiz = res.data;

  container.innerHTML = `
    <div style="margin-bottom: 20px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span class="eyebrow">{ MULTIPLE CHOICE }</span>
        <span class="pill-tag" style="color: var(--nest-crimson);">${currentQuiz.cefr_level || 'B1'}</span>
      </div>
      <div style="display: flex; align-items: baseline; gap: 12px; margin: 10px 0;">
        <div style="font-family: var(--font-display); font-size: 26px; font-weight: 700;">${currentQuiz.lemma}</div>
        <button onclick="speakWord('${currentQuiz.lemma.replace(/'/g, "\\'")}')" style="background: none; border: none; cursor: pointer; color: var(--pewter-text); font-size: 18px;">🔊</button>
      </div>
      ${currentQuiz.context_sentence ? `<div style="color: var(--pewter-text); font-size: 13px; margin-bottom: 12px;">💬 "${currentQuiz.context_sentence}"</div>` : ''}
      <div style="font-size: 12px; color: var(--pewter-text);">Выбери подходящий перевод:</div>
    </div>

    <div class="quiz-options-grid" id="quizOptionsGrid">
      ${currentQuiz.options.map(opt => `
        <button class="quiz-option-card" onclick="submitQuizAnswer('${opt.replace(/'/g, "\\'")}', this)">
          ${opt}
        </button>
      `).join('')}
    </div>
    <div id="quizFeedbackContainer" style="margin-top: 18px;"></div>
  `;
}

async function submitQuizAnswer(chosenOption, btn) {
  if (!currentQuiz) return;

  // Disable options
  document.querySelectorAll('.quiz-option-card').forEach(b => {
    b.style.pointerEvents = 'none';
  });

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
      btn.classList.add('correct');
    } else {
      btn.classList.add('wrong');
      // Highlight correct answer button
      document.querySelectorAll('.quiz-option-card').forEach(b => {
        if (b.innerText.trim() === res.data.correct_answer) {
          b.classList.add('correct');
        }
      });
    }

    if (feedback) {
      feedback.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-radius: 12px; background: ${isCorrect ? 'rgba(63,185,80,0.1)' : 'rgba(234,40,69,0.1)'}; border: 1px solid ${isCorrect ? 'var(--emerald-success)' : 'var(--nest-crimson)'};">
          <span>${isCorrect ? '🎉 <strong>Отлично!</strong> Верный ответ.' : `❌ <strong>Неверно.</strong> Правильный ответ: <strong>${res.data.correct_answer}</strong>`}</span>
          <button class="btn-primary" style="height: 36px; padding: 0 16px; font-size: 12px;" onclick="loadInteractiveQuiz()">Следующий ➔</button>
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

  container.innerHTML = '<div style="color: var(--pewter-text); text-align: center; padding: 60px 20px;">Подготовка очереди повторения FSRS...</div>';

  let url = '/cards/due?limit=25&interleave=true';
  if (studyTypeFilter && studyTypeFilter !== 'ALL') {
    url += `&card_type=${studyTypeFilter}`;
  }

  const res = await fetchAPI(url);
  if (!res.ok || !Array.isArray(res.data) || res.data.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 60px 20px;">
        <div style="font-size: 48px; margin-bottom: 16px;">🎉</div>
        <h3 style="font-family: var(--font-display); font-size: 22px; margin-bottom: 8px;">Все карточки на сегодня повторены!</h3>
        <p style="color: var(--pewter-text); max-width: 460px; margin: 0 auto 24px auto;">
          Интервалы FSRS рассчитаны. Новые повторения появятся согласно твоей кривой забывания.
        </p>
        <button class="btn-primary" onclick="navigate('/app/words')">Посмотреть колоду слов ➔</button>
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
      <div style="text-align: center; padding: 60px 20px;">
        <div style="font-size: 48px; margin-bottom: 16px;">🏆</div>
        <h3 style="font-family: var(--font-display); font-size: 22px; margin-bottom: 8px;">Сессия повторения завершена!</h3>
        <p style="color: var(--pewter-text); margin-bottom: 24px;">Ты повторил ${studyQueue.length} карточек. Прогресс сохранён в FSRS.</p>
        <button class="btn-primary" onclick="navigate('/app')">Вернуться в дашборд ➔</button>
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
      <div style="font-size: 11px; color: var(--pewter-text); margin-bottom: 8px; text-transform: uppercase;">{ EN ➔ RU: Вспомни русский перевод }</div>
      <div style="font-family: var(--font-display); font-size: 32px; font-weight: 700; color: #fff; margin-bottom: 12px;">
        ${word.lemma || ''}
      </div>
      ${word.example ? `<div style="color: var(--pewter-text); font-size: 14px;">💬 "${word.example.sentence_en}"</div>` : ''}
    `;
    backHtml = `
      <div style="font-size: 20px; font-weight: 600; color: var(--emerald-success); margin-bottom: 8px;">
        ${word.translation_ru || ''}
      </div>
      ${word.example ? `<div style="color: var(--pewter-text); font-size: 13px;">🇷🇺 "${word.example.sentence_ru}"</div>` : ''}
      ${word.grammar_note ? `<div style="font-size: 12px; color: #ffa657; margin-top: 8px;">💡 ${word.grammar_note}</div>` : ''}
    `;
  } else if (cType === 'ru_en') {
    frontHtml = `
      <div style="font-size: 11px; color: var(--pewter-text); margin-bottom: 8px; text-transform: uppercase;">{ RU ➔ EN: Активное воспроизведение }</div>
      <div style="font-family: var(--font-display); font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 12px;">
        ${word.translation_ru || ''}
      </div>
      ${word.example ? `<div style="color: var(--pewter-text); font-size: 14px;">💬 "${word.example.sentence_ru}"</div>` : ''}
    `;
    backHtml = `
      <div style="font-size: 28px; font-weight: 700; color: var(--bone-white); margin-bottom: 8px; display: flex; align-items: center; justify-content: center; gap: 12px;">
        <span>${word.lemma || ''}</span>
        <button onclick="speakWord('${(word.lemma || '').replace(/'/g, "\\'")}')" style="background: none; border: none; cursor: pointer; color: var(--pewter-text); font-size: 20px;">🔊</button>
      </div>
      ${word.transcription ? `<div style="color: var(--pewter-text); font-size: 13px; margin-bottom: 8px;">[${word.transcription}]</div>` : ''}
      ${word.example ? `<div style="color: var(--pewter-text); font-size: 13px;">💬 "${word.example.sentence_en}"</div>` : ''}
    `;
  } else if (cType === 'cloze') {
    const clozeEn = word.example && word.example.sentence_en
      ? word.example.sentence_en.replace(new RegExp(`\\b${word.lemma}\\b`, 'i'), '【 ... 】')
      : `Complete the sentence with: 【 ... 】`;
    frontHtml = `
      <div style="font-size: 11px; color: var(--pewter-text); margin-bottom: 8px; text-transform: uppercase;">{ CLOZE GAP: Заполни пропуск }</div>
      <div style="font-family: var(--font-display); font-size: 22px; font-weight: 600; color: #fff; line-height: 1.5; margin-bottom: 16px;">
        ${clozeEn}
      </div>
      <div style="color: var(--pewter-text); font-size: 13px;">Значение: ${word.translation_ru || ''}</div>
    `;
    backHtml = `
      <div style="font-size: 24px; font-weight: 700; color: var(--emerald-success); margin-bottom: 8px;">
        ${word.lemma || ''}
      </div>
      ${word.example ? `<div style="color: #fff; font-size: 14px;">💬 "${word.example.sentence_en}"</div>` : ''}
    `;
  } else {
    // Audio type
    frontHtml = `
      <div style="font-size: 11px; color: var(--pewter-text); margin-bottom: 8px; text-transform: uppercase;">{ AUDIO LISTENING: Распознавание на слух }</div>
      <div style="margin: 20px 0;">
        <button class="btn-primary" style="height: 52px; padding: 0 32px; font-size: 16px;" onclick="speakWord('${(word.lemma || '').replace(/'/g, "\\'")}')">
          🔊 Прослушать аудио
        </button>
      </div>
      <div style="color: var(--pewter-text); font-size: 12px;">Постарайся понять слово и его перевод на слух</div>
    `;
    backHtml = `
      <div style="font-family: var(--font-display); font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 6px;">
        ${word.lemma || ''}
      </div>
      <div style="font-size: 18px; color: var(--emerald-success); margin-bottom: 10px;">
        ${word.translation_ru || ''}
      </div>
      ${word.example ? `<div style="color: var(--pewter-text); font-size: 13px;">💬 "${word.example.sentence_en}"</div>` : ''}
    `;
  }

  container.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; font-size: 12px; color: var(--pewter-text);">
      <div>Карточка ${studyIndex + 1} из ${studyQueue.length}</div>
      <div style="display: flex; gap: 8px; align-items: center;">
        <span class="pill-tag">${cType.toUpperCase()}</span>
        <span class="pill-tag" style="color: var(--nest-crimson);">${word.cefr_level || 'B1'}</span>
      </div>
    </div>

    <!-- Front Face -->
    <div style="text-align: center; padding: 24px 16px; min-height: 120px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
      ${frontHtml}
    </div>

    <!-- Reveal Toggle or Back Face -->
    <div id="cardBackFace" style="display: ${isAnswerRevealed ? 'block' : 'none'}; border-top: 1px solid var(--smoke-outline); padding-top: 24px; margin-top: 20px; text-align: center;">
      ${backHtml}

      <!-- Rating Buttons (1 to 4) -->
      <div class="rating-buttons-grid" style="margin-top: 28px;">
        <button class="rating-btn again" onclick="submitCardRating(${card.id}, 1)">
          <div class="rating-num">1</div>
          <div class="rating-label">Снова</div>
          <div style="font-size: 10px; color: var(--pewter-text); margin-top: 2px;">Забыл</div>
        </button>
        <button class="rating-btn hard" onclick="submitCardRating(${card.id}, 2)">
          <div class="rating-num">2</div>
          <div class="rating-label">Трудно</div>
          <div style="font-size: 10px; color: var(--pewter-text); margin-top: 2px;">С усилием</div>
        </button>
        <button class="rating-btn good" onclick="submitCardRating(${card.id}, 3)">
          <div class="rating-num">3</div>
          <div class="rating-label">Хорошо</div>
          <div style="font-size: 10px; color: var(--pewter-text); margin-top: 2px;">Нормально</div>
        </button>
        <button class="rating-btn easy" onclick="submitCardRating(${card.id}, 4)">
          <div class="rating-num">4</div>
          <div class="rating-label">Легко</div>
          <div style="font-size: 10px; color: var(--pewter-text); margin-top: 2px;">Отлично помню</div>
        </button>
      </div>
    </div>

    <div id="revealBtnContainer" style="display: ${isAnswerRevealed ? 'none' : 'flex'}; justify-content: center; margin-top: 28px;">
      <button class="btn-primary" style="height: 48px; padding: 0 36px; font-size: 14px;" onclick="revealCardAnswer()">
        Показать ответ (Space) ➔
      </button>
    </div>
  `;
}

function revealCardAnswer() {
  isAnswerRevealed = true;
  const backFace = document.getElementById('cardBackFace');
  const revealBtn = document.getElementById('revealBtnContainer');
  if (backFace) backFace.style.display = 'block';
  if (revealBtn) revealBtn.style.display = 'none';
}

async function submitCardRating(cardId, rating) {
  // Post review to FSRS backend
  await fetchAPI(`/cards/${cardId}/review`, {
    method: 'POST',
    body: JSON.stringify({ rating: rating })
  });

  // Next card
  studyIndex++;
  isAnswerRevealed = false;
  renderCurrentStudyCard();
}

// Global hotkeys for study studio
document.addEventListener('keydown', (e) => {
  if (currentRoute !== '/app/study' || !studyQueue.length || studyIndex >= studyQueue.length) return;
  // Prevent if typing in an input/textarea
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

  container.innerHTML = '<div style="color: var(--pewter-text); padding: 40px; text-align: center; grid-column: 1 / -1;">Загрузка колоды слов...</div>';

  let url = `/words?page=${wordsState.page}&page_size=${wordsState.pageSize}`;
  if (wordsState.query) url += `&q=${encodeURIComponent(wordsState.query)}`;
  if (wordsState.cefr !== 'ALL') url += `&cefr_level=${wordsState.cefr}`;
  if (wordsState.status !== 'ALL') url += `&status=${wordsState.status}`;

  const res = await fetchAPI(url);
  if (!res.ok || !res.data) {
    container.innerHTML = '<div style="color: var(--pewter-text); padding: 40px; text-align: center; grid-column: 1 / -1;">Не удалось загрузить слова.</div>';
    return;
  }

  const items = res.data.items || [];
  wordsState.total = res.data.total || 0;

  if (items.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 60px 20px; color: var(--pewter-text);">
        По заданным фильтрам слов не найдено. Попробуй изменить фильтр или импортировать CSV.
      </div>
    `;
    if (pagination) pagination.innerHTML = '';
    return;
  }

  container.innerHTML = items.map(w => `
    <div class="word-card" id="wordCard-${w.id}">
      <div class="word-card-top">
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <div class="word-card-lemma">${w.lemma}</div>
          <span class="pill-tag" style="color: var(--nest-crimson);">${w.cefr_level || 'B1'}</span>
        </div>
        <div class="word-card-trans">${w.translation_ru}</div>
        ${w.notes ? `<div style="font-size: 11px; color: var(--pewter-text); margin-top: 6px;">📝 ${w.notes}</div>` : ''}
      </div>

      <div style="margin-top: 14px; border-top: 1px solid var(--smoke-outline); padding-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
        <select class="form-select" style="height: 32px; font-size: 11px; padding: 0 8px; width: 110px;" onchange="handleWordStatusChange(${w.id}, this.value)">
          <option value="learning" ${w.status === 'learning' ? 'selected' : ''}>Learning</option>
          <option value="mastered" ${w.status === 'mastered' ? 'selected' : ''}>Mastered</option>
        </select>

        <div style="display: flex; gap: 6px;">
          <button class="btn-secondary" style="height: 32px; padding: 0 10px;" title="Озвучить" onclick="speakWord('${w.lemma.replace(/'/g, "\\'")}')">🔊</button>
          <button class="btn-secondary" style="height: 32px; padding: 0 10px; color: var(--nest-crimson);" title="Удалить из колоды" onclick="handleDeleteWord(${w.id})">🗑️</button>
        </div>
      </div>
    </div>
  `).join('');

  // Render pagination
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
    html += `<button class="btn-secondary" style="height: 34px; padding: 0 12px; font-size: 12px;" onclick="goToWordsPage(${wordsState.page - 1})">◀ Назад</button>`;
  }
  html += `<span style="font-size: 12px; color: var(--pewter-text); padding: 8px 12px;">Стр. ${wordsState.page} из ${totalPages} (${wordsState.total} слов)</span>`;
  if (wordsState.page < totalPages) {
    html += `<button class="btn-secondary" style="height: 34px; padding: 0 12px; font-size: 12px;" onclick="goToWordsPage(${wordsState.page + 1})">Вперёд ▶</button>`;
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
  if (!confirm('Удалить это слово и все связанные карточки из твоей колоды?')) return;
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
    alert(`Импорт завершён!\nУспешно добавлено: ${res.data.imported_count} слов\nПропущено дубликатов: ${res.data.skipped_duplicates}`);
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

  if (chartContainer) chartContainer.innerHTML = '<div style="color: var(--pewter-text);">Загрузка аналитики...</div>';

  const res = await fetchAPI('/profile/analytics');
  if (!res.ok || !res.data) {
    if (chartContainer) chartContainer.innerHTML = '<div style="color: var(--pewter-text);">Не удалось загрузить данные аналитики.</div>';
    return;
  }

  const an = res.data;

  // Score
  if (scoreBadge) {
    const rVal = an.retention_30d !== undefined ? an.retention_30d : 95.0;
    scoreBadge.textContent = `Retention 30d: ${Number(rVal).toFixed(1)}%`;
  }

  // 1. Retention SVG Chart
  if (chartContainer && an.retention_daily) {
    renderRetentionSvgChart(chartContainer, an.retention_daily);
  }

  // 2. Card Types Accuracy
  if (cardTypesContainer && an.card_type_accuracy) {
    const types = [
      { key: 'en_ru', label: 'EN ➔ RU (Recall)' },
      { key: 'ru_en', label: 'RU ➔ EN (Active Recall)' },
      { key: 'cloze', label: 'Cloze Gap (Context)' },
      { key: 'audio', label: 'Audio Listening' }
    ];
    cardTypesContainer.innerHTML = types.map(t => {
      const acc = an.card_type_accuracy[t.key] !== undefined ? an.card_type_accuracy[t.key] : 100;
      return `
        <div>
          <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
            <span>${t.label}</span>
            <span style="font-weight: 600; color: ${acc >= 85 ? 'var(--emerald-success)' : '#ffa657'};">${Number(acc).toFixed(1)}%</span>
          </div>
          <div style="background: var(--ash-seam); height: 6px; border-radius: 999px; overflow: hidden;">
            <div style="background: ${acc >= 85 ? 'var(--emerald-success)' : '#ffa657'}; width: ${acc}%; height: 100%; border-radius: 999px;"></div>
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
      const dayLabel = d.date.slice(5); // MM-DD
      return `
        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; height: 100%; justify-content: flex-end;">
          <div style="font-size: 11px; font-weight: 600; color: var(--pewter-text);">${d.due_count}</div>
          <div style="width: 100%; background: linear-gradient(180deg, var(--nest-crimson), #780f20); border-radius: 4px; height: ${Math.max(8, heightPct)}%;"></div>
          <div style="font-size: 10px; color: var(--pewter-text);">${dayLabel}</div>
        </div>
      `;
    }).join('');
  }

  // 4. Problem Words
  if (problemContainer && an.problem_words) {
    if (an.problem_words.length === 0) {
      problemContainer.innerHTML = '<div style="color: var(--pewter-text); font-size: 13px;">Сложных слов с частыми ошибками пока нет. Отличная память!</div>';
    } else {
      problemContainer.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 8px;">
          ${an.problem_words.map(pw => `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--carbon-panel); border: 1px solid var(--smoke-outline); border-radius: 10px;">
              <div>
                <strong style="font-family: var(--font-display);">${pw.lemma}</strong>
                <span style="color: var(--pewter-text); font-size: 12px; margin-left: 8px;">— ${pw.translation_ru}</span>
              </div>
              <div style="display: flex; gap: 12px; align-items: center; font-size: 12px;">
                <span style="color: var(--nest-crimson);">Ошибок (Lapses): ${pw.lapses}</span>
                <span style="color: var(--pewter-text);">Стабильность: ${Number(pw.stability || 0).toFixed(1)}d</span>
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
    container.innerHTML = '<div style="color: var(--pewter-text);">Недостаточно данных для графика.</div>';
    return;
  }

  const width = 800;
  const height = 160;
  const padLeft = 40;
  const padRight = 20;
  const padTop = 15;
  const padBottom = 25;

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
      <line x1="${padLeft}" y1="${padTop}" x2="${width - padRight}" y2="${padTop}" stroke="var(--smoke-outline)" stroke-dasharray="3 3"/>
      <line x1="${padLeft}" y1="${padTop + chartH * 0.5}" x2="${width - padRight}" y2="${padTop + chartH * 0.5}" stroke="var(--smoke-outline)" stroke-dasharray="3 3"/>
      <line x1="${padLeft}" y1="${padTop + chartH}" x2="${width - padRight}" y2="${padTop + chartH}" stroke="var(--smoke-outline)"/>

      <!-- Labels -->
      <text x="${padLeft - 8}" y="${padTop + 4}" fill="var(--pewter-text)" font-size="10" text-anchor="end">100%</text>
      <text x="${padLeft - 8}" y="${padTop + chartH * 0.5 + 4}" fill="var(--pewter-text)" font-size="10" text-anchor="end">50%</text>
      <text x="${padLeft - 8}" y="${padTop + chartH + 4}" fill="var(--pewter-text)" font-size="10" text-anchor="end">0%</text>

      <!-- Curve Area & Line -->
      <polyline fill="none" stroke="var(--nest-crimson)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${polylineStr}" />

      <!-- Dots -->
      ${points.map(p => `
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="#fff" stroke="var(--nest-crimson)" stroke-width="2">
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
    alert('Настройки профиля успешно сохранены! ✅');
  } else {
    alert('Ошибка при сохранении: ' + (res.data ? res.data.detail : 'Проверьте поля'));
  }
}

// Entrypoint initialization
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('appRoot')) {
    renderRoute();
  }
});
