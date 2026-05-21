/* ===========================
   TAJFUN LAB – script.js
   Tydzień 1, Dzień 1
=========================== */

(function () {
  'use strict';

  const slides = document.querySelectorAll('.slide');
  const btnPrev = document.getElementById('btnPrev');
  const btnNext = document.getElementById('btnNext');
  const dotsContainer = document.getElementById('dots');
  const slideCounter = document.getElementById('slideCounter');
  const total = slides.length;

  let current = 0;
  let isAnimating = false;

  /* ---- Build dots ---- */
  slides.forEach((_, i) => {
    const dot = document.createElement('span');
    dot.classList.add('dot');
    if (i === 0) dot.classList.add('active');
    dot.addEventListener('click', () => goTo(i));
    dotsContainer.appendChild(dot);
  });

  const dots = dotsContainer.querySelectorAll('.dot');

  /* ---- Initial state ---- */
  updateUI();

  /* ---- Button listeners ---- */
  btnPrev.addEventListener('click', () => {
    if (current > 0 && !isAnimating) goTo(current - 1, 'prev');
  });

  btnNext.addEventListener('click', () => {
    if (current < total - 1 && !isAnimating) goTo(current + 1, 'next');
  });

  /* ---- Keyboard ---- */
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      if (current < total - 1 && !isAnimating) goTo(current + 1, 'next');
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      if (current > 0 && !isAnimating) goTo(current - 1, 'prev');
    }
  });

  /* ---- Touch / Swipe ---- */
  let touchStartX = 0;
  let touchStartY = 0;

  document.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  }, { passive: true });

  document.addEventListener('touchend', (e) => {
    if (isAnimating) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    const dy = e.changedTouches[0].clientY - touchStartY;
    if (Math.abs(dx) < Math.abs(dy) * 0.7) return; // mostly vertical — ignore
    if (Math.abs(dx) < 40) return; // too short
    if (dx < 0 && current < total - 1) goTo(current + 1, 'next');
    if (dx > 0 && current > 0) goTo(current - 1, 'prev');
  }, { passive: true });

  /* ---- Navigate ---- */
  function goTo(index, direction) {
    if (index === current || isAnimating) return;
    isAnimating = true;
    direction = direction || (index > current ? 'next' : 'prev');

    const outgoing = slides[current];
    const incoming = slides[index];

    // Set incoming starting position
    if (direction === 'next') {
      incoming.style.transform = 'translateX(60px)';
    } else {
      incoming.style.transform = 'translateX(-60px)';
    }
    incoming.style.opacity = '0';
    incoming.style.transition = 'none';
    incoming.classList.add('active');

    // Force reflow
    void incoming.offsetWidth;

    // Animate incoming in
    incoming.style.transition = '';
    incoming.style.transform = 'translateX(0)';
    incoming.style.opacity = '1';

    // Animate outgoing out
    if (direction === 'next') {
      outgoing.style.transform = 'translateX(-60px)';
    } else {
      outgoing.style.transform = 'translateX(60px)';
    }
    outgoing.style.opacity = '0';
    outgoing.style.transition = 'opacity 0.32s ease, transform 0.32s ease';

    setTimeout(() => {
      outgoing.classList.remove('active');
      outgoing.style.transform = '';
      outgoing.style.opacity = '';
      outgoing.style.transition = '';
      incoming.style.transform = '';
      incoming.style.opacity = '';
      incoming.style.transition = '';
      current = index;
      updateUI();
      isAnimating = false;
    }, 340);
  }

  /* ---- Update counter, dots, buttons ---- */
  function updateUI() {
    slideCounter.textContent = (current + 1) + ' / ' + total;

    dots.forEach((d, i) => {
      d.classList.toggle('active', i === current);
    });

    btnPrev.disabled = current === 0;
    btnNext.disabled = current === total - 1;

    // Change next button text on last slide
    if (current === total - 1) {
      btnNext.textContent = 'Koniec';
    } else {
      btnNext.textContent = 'Dalej →';
    }

    if (current === 0) {
      btnPrev.textContent = '← Wstecz';
    }
  }

})();
