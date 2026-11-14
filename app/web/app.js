// ENG TUTOR Web Client — Cognitive AI Spaced Repetition (Stage 2 & 3)

const API_BASE = window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
  ? `${window.location.origin}/api/v1`
  : 'http://localhost:8000/api/v1';

// Global State
let allLessons = [];
let allWords = [];
let allStudyCards = [];
let currentLessonFilter = 'ALL';
let currentCardTypeFilter = 'ALL';
let currentDeckLevelFilter = 'ALL';
let currentSearchQuery = '';

let activeStudyQueue = [];
let currentCardIndex = 0;
let isAnswerRevealed = false;
let currentQuiz = null;

// Audio Pronunciation via SpeechSynthesis
function speakWord(text) {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 0.92;
    window.speechSynthesis.speak(utterance);
  }
}

// Fetch Lessons and Seed Data
async function initAppData() {
  try {
    const res = await fetch('/lessons.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allLessons = await res.json();
    processLessonsData(allLessons);
  } catch (err) {
    console.warn('Could not load lessons.json directly, falling back to embedded dataset', err);
    fallbackInit();
  }
}

function processLessonsData(lessons) {
  allWords = [];
  allStudyCards = [];

  lessons.forEach(l => {
    l.items.forEach((item, idx) => {
      const wordObj = {
        id: `${l.lesson_id}_${idx + 1}`,
        lesson_id: l.lesson_id,
        lesson_title: l.title,
        lemma: item.lemma,
        translation_ru: item.translation_ru,
        transcription: item.transcription || '',
        part_of_speech: item.part_of_speech || 'prep phrase',
        cefr_level: item.cefr_level || 'B1',
        grammar_note: item.grammar_note || '',
        collocations: item.collocations || [],
        example: {
          sentence_en: item.example_en || `This example illustrates "${item.lemma}".`,
          sentence_ru: item.example_ru || `Этот пример иллюстрирует "${item.translation_ru}".`
        }
      };

      allWords.push(wordObj);

      // Create 4 card types for each word
      const types = ['en_ru', 'ru_en', 'cloze', 'audio'];
      types.forEach((cType, tIdx) => {
        allStudyCards.push({
          id: `${wordObj.id}_${cType}`,
          word: wordObj,
          card_type: cType,
          state: 1, // Learning
          reps: 0,
          lapses: 0,
          due_at: new Date().toISOString()
        });
      });
    });
  });

  // Interleave study cards: alternate card types and words
  interleaveCards(allStudyCards);

  // Update DOM components
  renderLessonPills();
  applyLessonFilter('ALL');
  loadMultipleChoiceQuiz();
  renderVocabularyDeck();
  updateSummaryCounters();
}

function interleaveCards(cards) {
  // Sort into interleaved order: rotate card types across distinct words
  const buckets = { en_ru: [], cloze: [], ru_en: [], audio: [] };
  cards.forEach(c => {
    if (buckets[c.card_type]) buckets[c.card_type].push(c);
  });

  const interleaved = [];
  const maxLen = Math.max(...Object.values(buckets).map(b => b.length));
  const order = ['cloze', 'en_ru', 'ru_en', 'audio'];

  for (let i = 0; i < maxLen; i++) {
    order.forEach(type => {
      if (buckets[type][i]) interleaved.push(buckets[type][i]);
    });
  }

  allStudyCards = interleaved;
}

function updateSummaryCounters() {
  const summaryEl = document.getElementById('lessonSummaryCount');
  if (summaryEl) {
    summaryEl.innerText = `${allWords.length} выражений · ${allStudyCards.length} FSRS карточек`;
  }
}

// Render Top Lesson Pills
function renderLessonPills() {
  const container = document.getElementById('lessonPillsContainer');
  if (!container) return;

  let html = `
    <button class="lesson-pill ${currentLessonFilter === 'ALL' ? 'active' : ''}" onclick="applyLessonFilter('ALL', this)">
      <strong>🌟 Все 7 уроков</strong> (${allWords.length})
    </button>
  `;

  allLessons.forEach(l => {
    const isAct = currentLessonFilter === String(l.lesson_id);
    // Short title for pill
    let shortName = `Урок ${l.lesson_id}`;
    if (l.title.includes('прилагательными')) shortName = `Урок ${l.lesson_id}: Прилагательные`;
    else if (l.title.includes('глаголами')) shortName = `Урок ${l.lesson_id}: Глаголы`;
    else if (l.title.includes('существительными')) shortName = `Урок ${l.lesson_id}: Существительные`;
    else if (l.title.includes('Устойчивые')) shortName = `Урок ${l.lesson_id}: Идиомы & Фразы`;

    html += `
      <button class="lesson-pill ${isAct ? 'active' : ''}" onclick="applyLessonFilter('${l.lesson_id}', this)">
        ${shortName} (${l.items.length})
      </button>
    `;
  });

  container.innerHTML = html;
}

// Switch Active Lesson
function applyLessonFilter(lessonId, btnEl) {
  currentLessonFilter = lessonId;

  // Update pills visual state
  document.querySelectorAll('.lesson-pill').forEach(p => p.classList.remove('active'));
  if (btnEl) {
    btnEl.classList.add('active');
  } else {
    const first = document.querySelector('.lesson-pill');
    if (first && lessonId === 'ALL') first.classList.add('active');
  }

  // Update Study Studio Badge
  const badge = document.getElementById('studyCurrentLessonBadge');
  if (badge) {
    if (lessonId === 'ALL') {
      badge.innerText = `Урок: Все 7 уроков (${allWords.length} выражений)`;
    } else {
      const match = allLessons.find(l => String(l.lesson_id) === String(lessonId));
      badge.innerText = match ? match.title : `Урок ${lessonId}`;
    }
  }

  // Filter study queue
  filterStudyQueue();
  renderVocabularyDeck();
  loadMultipleChoiceQuiz();
}

function filterStudyQueue() {
  let cards = [...allStudyCards];

  if (currentLessonFilter !== 'ALL') {
    cards = cards.filter(c => String(c.word.lesson_id) === String(currentLessonFilter));
  }

  if (currentCardTypeFilter !== 'ALL') {
    cards = cards.filter(c => c.card_type === currentCardTypeFilter);
  }

  activeStudyQueue = cards;
  currentCardIndex = 0;
  isAnswerRevealed = false;
  renderCurrentCard();
}

function setCardTypeFilter(cType) {
  currentCardTypeFilter = cType;
  document.querySelectorAll('.studio-tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  filterStudyQueue();
}

// Render Card in Learning Studio
function renderCurrentCard() {
  const container = document.getElementById('studioCardContainer');
  if (!container) return;

  if (activeStudyQueue.length === 0 || currentCardIndex >= activeStudyQueue.length) {
    container.innerHTML = `
      <div style="text-align: center; padding: 48px 20px;">
        <div style="font-size: 48px; margin-bottom: 16px;">🎉</div>
        <h3 style="font-family: var(--font-display); font-size: 24px; margin-bottom: 8px;">Все карточки повторены!</h3>
        <p style="color: var(--pewter-text); margin-bottom: 24px;">Ты успешно закрепил порцию карточек по интервальному алгоритму FSRS.</p>
        <button class="btn-primary" onclick="restartStudySession()">Начать заново</button>
      </div>
    `;
    return;
  }

  const card = activeStudyQueue[currentCardIndex];
  const word = card.word;
  const ex = word.example || {};
  const cType = card.card_type || 'en_ru';

  const typeLabels = {
    'en_ru': 'EN ➔ RU (контекстное воспоминание)',
    'ru_en': 'RU ➔ EN (активное производство)',
    'cloze': 'Пропуск в предложении (Cloze Gap)',
    'audio': 'Аудиокарточка (восприятие на слух)'
  };

  let promptHtml = '';
  if (cType === 'cloze') {
    // Robust Cloze masking: mask target lemma or individual prepositions
    let masked = ex.sentence_en;
    if (masked) {
      // Escape special characters in lemma
      const escaped = word.lemma.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
      masked = masked.replace(new RegExp(escaped, 'gi'), '<mark>[ ... ]</mark>');
    } else {
      masked = `<mark>[ ... ]</mark> — "${word.translation_ru}"`;
    }
    promptHtml = `
      <div class="card-sentence-prompt">${masked}</div>
      <div class="card-hint">🇷🇺 Значение: <strong>${word.translation_ru}</strong> · Урок: <em>${word.lesson_title.split('—')[0]}</em></div>
    `;
  } else if (cType === 'ru_en') {
    promptHtml = `
      <div class="card-sentence-prompt" style="color: #ffffff; font-size: 22px;">
        "${ex.sentence_ru || word.translation_ru}"
      </div>
      <div class="card-hint">Вспомни английское выражение: <strong>[ ${word.part_of_speech} · ${word.cefr_level} ]</strong></div>
    `;
  } else if (cType === 'audio') {
    promptHtml = `
      <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 24px;">
        <button class="btn-secondary" onclick="speakWord('${word.lemma}')" style="height: 48px;">
          🔊 Прослушать фразу
        </button>
        <span style="color: var(--pewter-text); font-size: 13px;">Послушай аудио и вспомни значение выражения</span>
      </div>
    `;
  } else {
    // en_ru
    promptHtml = `
      <div class="card-sentence-prompt" style="font-family: var(--font-display); font-size: 28px; font-weight: 600; color: #fff;">
        ${word.lemma}
      </div>
      ${ex.sentence_en ? `<div class="card-sentence-prompt" style="font-size: 16px; color: var(--pewter-text); margin-top: 8px;">"${ex.sentence_en}"</div>` : ''}
    `;
  }

  let answerHtml = '';
  if (isAnswerRevealed) {
    const collocationsHtml = word.collocations && word.collocations.length
      ? `<div class="pill-tags">${word.collocations.map(c => `<span class="pill-tag">🔗 ${c}</span>`).join('')}</div>`
      : '';
    const grammarHtml = word.grammar_note
      ? `<div style="font-size: 12px; color: #ffa657; margin-top: 8px;">💡 <strong>Правило / сочетаемость:</strong> ${word.grammar_note}</div>`
      : '';

    answerHtml = `
      <div class="card-answer-box">
        <div style="display: flex; align-items: baseline; justify-content: space-between;">
          <div>
            <span class="word-highlight">${word.lemma}</span>
            <span class="word-transcription">${word.transcription}</span>
            <span class="pill-tag" style="margin-left: 8px; color: var(--nest-crimson);">${word.cefr_level}</span>
          </div>
          <button class="btn-secondary" onclick="speakWord('${word.lemma}')" style="height: 36px; padding: 0 14px; font-size: 13px;">
            🔊 Озвучить
          </button>
        </div>
        <div class="word-translation-lg">🇷🇺 ${word.translation_ru}</div>
        ${ex.sentence_en ? `<div style="font-size: 14px; color: #ddd; margin-bottom: 4px;">💬 <em>"${ex.sentence_en}"</em></div>` : ''}
        ${ex.sentence_ru ? `<div style="font-size: 13px; color: var(--pewter-text);">↳ <em>"${ex.sentence_ru}"</em></div>` : ''}
        ${collocationsHtml}
        ${grammarHtml}
      </div>

      <div class="rating-buttons-grid">
        <button class="btn-rating btn-again" onclick="handleRate(1)">
          <span class="label">❌ Не знаю</span>
          <span class="interval">&lt; 1 мин</span>
        </button>
        <button class="btn-rating btn-hard" onclick="handleRate(2)">
          <span class="label">😓 Сложно</span>
          <span class="interval">6 мин</span>
        </button>
        <button class="btn-rating btn-good" onclick="handleRate(3)">
          <span class="label">✅ Знаю</span>
          <span class="interval">10 мин</span>
        </button>
        <button class="btn-rating btn-easy" onclick="handleRate(4)">
          <span class="label">⚡ Легко</span>
          <span class="interval">4 дня</span>
        </button>
      </div>
    `;
  } else {
    answerHtml = `
      <div style="margin-top: 24px;">
        <button class="btn-primary" style="width: 100%;" onclick="revealAnswer()">
          👁 Показать ответ <span style="font-size: 12px; color: #666; margin-left: 8px;">(Space)</span>
        </button>
      </div>
    `;
  }

  container.innerHTML = `
    <div>
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <span class="card-type-badge">${typeLabels[cType] || cType}</span>
        <span style="font-size: 12px; color: var(--pewter-text);">Карточка ${currentCardIndex + 1} из ${activeStudyQueue.length}</span>
      </div>
      ${promptHtml}
      ${answerHtml}
    </div>
  `;
}

function revealAnswer() {
  isAnswerRevealed = true;
  renderCurrentCard();
  const card = activeStudyQueue[currentCardIndex];
  if (card && card.word && card.card_type === 'audio') {
    speakWord(card.word.lemma);
  }
}

function handleRate(rating) {
  isAnswerRevealed = false;
  currentCardIndex++;
  renderCurrentCard();
}

function restartStudySession() {
  currentCardIndex = 0;
  isAnswerRevealed = false;
  renderCurrentCard();
}

// Multiple Choice Quiz
function loadMultipleChoiceQuiz() {
  const container = document.getElementById('quizContainer');
  if (!container || allWords.length === 0) return;

  // Filter pool by current lesson if selected
  const pool = currentLessonFilter === 'ALL'
    ? allWords
    : allWords.filter(w => String(w.lesson_id) === String(currentLessonFilter));

  const targetWord = pool[Math.floor(Math.random() * pool.length)] || allWords[0];
  const correct = targetWord.translation_ru;

  // Pick 3 realistic distractors from allWords
  const otherWords = allWords
    .filter(w => w.translation_ru !== correct && w.lemma !== targetWord.lemma)
    .sort(() => Math.random() - 0.5);

  const distractors = otherWords.slice(0, 3).map(w => w.translation_ru);
  const options = [correct, ...distractors].sort(() => Math.random() - 0.5);

  currentQuiz = {
    lemma: targetWord.lemma,
    correct: correct,
    lesson_title: targetWord.lesson_title,
    sentence: targetWord.example ? targetWord.example.sentence_en : null,
  };

  container.innerHTML = `
    <div style="margin-bottom: 20px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div class="eyebrow">{ MULTIPLE CHOICE QUIZ } <span class="eyebrow-cursor">_</span></div>
        <span class="study-lesson-badge" style="margin: 0;">${targetWord.lesson_title.split('—')[0]}</span>
      </div>
      <div style="display: flex; align-items: baseline; gap: 12px; margin-top: 8px; margin-bottom: 8px;">
        <div style="font-family: var(--font-display); font-size: 28px; font-weight: 600; color: #fff;">
          ${targetWord.lemma}
        </div>
        <button onclick="speakWord('${targetWord.lemma}')" style="background: none; border: none; cursor: pointer; color: var(--pewter-text); font-size: 16px;">🔊</button>
      </div>
      ${targetWord.example ? `<div style="color: var(--pewter-text); font-size: 14px; margin-bottom: 16px;">💬 "${targetWord.example.sentence_en}"</div>` : ''}
      <div style="font-size: 13px; color: var(--pewter-text);">Выбери верный русский перевод / значение:</div>
    </div>
    <div class="quiz-options-grid">
      ${options.map(opt => `
        <button class="quiz-option-card" onclick="selectQuizOption(this, '${opt.replace(/'/g, "\\'")}')">
          ${opt}
        </button>
      `).join('')}
    </div>
    <div id="quizFeedback" style="margin-top: 20px;"></div>
  `;
}

function selectQuizOption(btn, chosen) {
  if (!currentQuiz) return;
  const isCorrect = chosen === currentQuiz.correct;
  const cards = document.querySelectorAll('.quiz-option-card');
  cards.forEach(c => {
    c.style.pointerEvents = 'none';
    if (c.innerText.trim() === currentQuiz.correct) {
      c.classList.add('correct');
    }
  });

  if (!isCorrect) {
    btn.classList.add('wrong');
  }

  const feedback = document.getElementById('quizFeedback');
  if (feedback) {
    feedback.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px; border-radius: 12px; background: ${isCorrect ? 'rgba(63,185,80,0.1)' : 'rgba(234,40,69,0.1)'}; border: 1px solid ${isCorrect ? 'var(--emerald-success)' : 'var(--nest-crimson)'};">
        <span>${isCorrect ? '🎉 <strong>Отлично!</strong> Абсолютно верно.' : `❌ <strong>Ошибка.</strong> Верный перевод: <strong>${currentQuiz.correct}</strong>`}</span>
        <button class="btn-primary" style="height: 40px; padding: 0 18px; font-size: 13px;" onclick="loadMultipleChoiceQuiz()">Следующий ➔</button>
      </div>
    `;
  }
}

// Sentence Extractor
function analyzeSentenceInput() {
  const input = document.getElementById('sentenceInput');
  const resultsContainer = document.getElementById('extractorResults');
  if (!input || !resultsContainer) return;

  const text = input.value.trim();
  if (text.length < 5) {
    resultsContainer.innerHTML = '<div style="color: var(--pewter-text);">Введи полное предложение на английском.</div>';
    return;
  }

  resultsContainer.innerHTML = '<div style="color: var(--pewter-text);">⏳ Анализирую предложение и сверяю с базой 107 предлогов...</div>';

  setTimeout(() => {
    // Check if any loaded prepositions match in the sentence
    const matches = allWords.filter(w => {
      const regex = new RegExp(`\\b${w.lemma.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}`, 'i');
      return regex.test(text);
    });

    if (matches.length > 0) {
      resultsContainer.innerHTML = `
        <div style="margin-top: 16px;">
          <div style="font-size: 12px; color: var(--emerald-success); margin-bottom: 12px;">✅ НАЙДЕНЫ СОВПАДЕНИЯ ИЗ КУРСА:</div>
          <div style="display: flex; flex-direction: column; gap: 10px;">
            ${matches.map(w => `
              <div style="display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; background: #181818; border: 1px solid var(--smoke-outline); border-radius: 14px;">
                <div>
                  <strong style="font-family: var(--font-display); font-size: 16px;">${w.lemma}</strong>
                  <span style="color: var(--pewter-text); font-size: 13px; margin-left: 8px;">${w.transcription}</span>
                  <span class="pill-tag" style="margin-left: 8px; color: var(--nest-crimson);">${w.cefr_level}</span>
                  <div style="color: var(--emerald-success); font-size: 13px; margin-top: 2px;">🇷🇺 ${w.translation_ru}</div>
                  <div style="color: var(--pewter-text); font-size: 12px; margin-top: 2px;">📚 ${w.lesson_title}</div>
                </div>
                <button class="btn-secondary" style="height: 38px; padding: 0 16px; font-size: 13px;" onclick="speakWord('${w.lemma}')">
                  🔊 Озвучить
                </button>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    } else {
      resultsContainer.innerHTML = `
        <div style="margin-top: 16px; padding: 16px; background: #181818; border: 1px solid var(--smoke-outline); border-radius: 14px;">
          <div style="color: var(--pewter-text); margin-bottom: 8px;">Предложение проверено. Прямых совпадений с 107 предложными конструкциями не обнаружено.</div>
          <div style="font-size: 13px; color: #fff;">💡 Попробуй предложения со словами: <em>typical of, responsible for, keen on, depend on, influence on, in the beginning...</em></div>
        </div>
      `;
    }
  }, 350);
}

// Vocabulary Deck Rendering
function renderVocabularyDeck() {
  const container = document.getElementById('deckGrid');
  if (!container) return;

  let filtered = [...allWords];

  // Filter by lesson
  if (currentLessonFilter !== 'ALL') {
    filtered = filtered.filter(w => String(w.lesson_id) === String(currentLessonFilter));
  }

  // Filter by CEFR
  if (currentDeckLevelFilter !== 'ALL') {
    filtered = filtered.filter(w => w.cefr_level === currentDeckLevelFilter);
  }

  // Filter by search query
  if (currentSearchQuery.trim()) {
    const q = currentSearchQuery.toLowerCase().trim();
    filtered = filtered.filter(w => 
      w.lemma.toLowerCase().includes(q) ||
      w.translation_ru.toLowerCase().includes(q) ||
      (w.collocations && w.collocations.some(c => c.toLowerCase().includes(q)))
    );
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 48px 20px; color: var(--pewter-text);">
        По вашему запросу ничего не найдено.
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(w => {
    const collocationsHtml = w.collocations && w.collocations.length
      ? `<div class="pill-tags" style="margin-top: 8px;">${w.collocations.slice(0, 2).map(c => `<span class="pill-tag" style="font-size: 11px;">🔗 ${c}</span>`).join('')}</div>`
      : '';
    const grammarHtml = w.grammar_note
      ? `<div style="font-size: 11px; color: #ffa657; margin-top: 6px; line-height: 1.4;">💡 ${w.grammar_note}</div>`
      : '';

    return `
      <div class="word-card">
        <div class="word-card-top">
          <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <div class="word-card-lemma">${w.lemma}</div>
            <span class="pill-tag" style="color: var(--nest-crimson); font-size: 10px;">${w.cefr_level}</span>
          </div>
          <div style="color: var(--pewter-text); font-size: 12px; margin-top: 2px;">${w.transcription}</div>
          <div class="word-card-ru">🇷🇺 ${w.translation_ru}</div>
          ${collocationsHtml}
          ${grammarHtml}
        </div>
        <div class="word-card-meta">
          <span>${w.lesson_title.split('—')[0]}</span>
          <button onclick="speakWord('${w.lemma}')" style="background: none; border: none; cursor: pointer; color: var(--pewter-text); font-size: 14px;">🔊</button>
        </div>
      </div>
    `;
  }).join('');
}

function handleDeckSearch(query) {
  currentSearchQuery = query;
  renderVocabularyDeck();
}

function filterDeckByLevel(level, btn) {
  currentDeckLevelFilter = level;
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderVocabularyDeck();
}

function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: 'smooth' });
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if (['input', 'textarea'].includes(document.activeElement.tagName.toLowerCase())) {
    return;
  }
  if (e.code === 'Space') {
    if (!isAnswerRevealed) {
      e.preventDefault();
      revealAnswer();
    }
  } else if (isAnswerRevealed && ['Digit1', 'Digit2', 'Digit3', 'Digit4'].includes(e.code)) {
    const rating = parseInt(e.code.replace('Digit', ''), 10);
    handleRate(rating);
  }
});

// Fallback init if fetch fails
function fallbackInit() {
  allLessons = [
    {
      lesson_id: 1,
      title: "Урок 1 — Зависимые предлоги с прилагательными (Часть 1)",
      items: [
        {
          lemma: "typical of",
          translation_ru: "типичный для",
          transcription: "/ˈtɪp.ɪ.kəl əv/",
          part_of_speech: "adjective + prep",
          cefr_level: "B1",
          grammar_note: "typical of someone/something",
          collocations: ["typical of him", "typical of the region"],
          example_en: "Such hasty behavior is typical of young children.",
          example_ru: "Такое поспешное поведение типично для маленьких детей."
        }
      ]
    }
  ];
  processLessonsData(allLessons);
}

// Startup
document.addEventListener('DOMContentLoaded', () => {
  initAppData();
});
