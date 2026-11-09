'use strict';

const form = document.getElementById('login-form');
const password = document.getElementById('password');
const error = document.getElementById('error');
const submit = document.getElementById('submit');

form.addEventListener('submit', async event => {
  event.preventDefault();
  error.hidden = true;
  submit.disabled = true;
  submit.textContent = 'Signing in…';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({password: password.value}),
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('That password was not accepted. Please try again.');
    window.location.replace('/');
  } catch (reason) {
    error.textContent = reason instanceof Error ? reason.message : 'Sign-in failed. Please try again.';
    error.hidden = false;
    password.focus();
    password.select();
  } finally {
    submit.disabled = false;
    submit.innerHTML = 'Sign in <span aria-hidden="true">→</span>';
  }
});
