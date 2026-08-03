(function() {
  var button = document.querySelector('[data-marcus-splash]');
  if (!button) return;

  var splashZone = button.closest('.marcus-splash-zone');
  var droplets = ['💦', '💧', '💦', '💧', '💦', '🌊'];
  var clickCount = 0;

  button.addEventListener('click', function() {
    clickCount++;
    button.classList.remove('is-shaking');
    void button.offsetWidth;
    button.classList.add('is-shaking');

    for (var i = 0; i < 14; i++) {
      var angle = (Math.PI * 2 * i / 14) + (Math.random() - 0.5) * 0.45;
      var distance = 75 + Math.random() * 85;
      var droplet = document.createElement('span');

      droplet.className = 'water-splash';
      droplet.textContent = droplets[Math.floor(Math.random() * droplets.length)];
      droplet.setAttribute('aria-hidden', 'true');
      droplet.style.setProperty('--splash-x', Math.cos(angle) * distance + 'px');
      droplet.style.setProperty('--splash-y', Math.sin(angle) * distance + 'px');
      droplet.style.setProperty('--splash-rotation', (Math.random() * 120 - 60) + 'deg');
      droplet.style.setProperty('--splash-size', (1.1 + Math.random() * 0.9) + 'rem');
      splashZone.appendChild(droplet);

      window.setTimeout(function(element) {
        element.remove();
      }, 900, droplet);
    }

    if (clickCount === 10) {
      button.disabled = true;
      button.setAttribute('aria-label', 'Marcus is swimming away with the website');
      button.classList.add('is-swimming-away');

      window.setTimeout(function() {
        document.body.classList.add('site-swimming-away');

        window.setTimeout(function() {
          var orbitRing = document.createElement('div');
          orbitRing.className = 'marcus-orbit-ring';
          orbitRing.setAttribute('aria-hidden', 'true');

          for (var i = 0; i < 8; i++) {
            var orbitingMarcus = document.createElement('img');
            orbitingMarcus.className = 'orbiting-marcus';
            orbitingMarcus.src = '/assets/images/marcus-large.png';
            orbitingMarcus.alt = '';
            orbitingMarcus.style.setProperty('--orbit-angle', (i * 45) + 'deg');
            orbitRing.appendChild(orbitingMarcus);
          }

          var rickrollButton = document.createElement('button');
          rickrollButton.type = 'button';
          rickrollButton.className = 'btn btn-primary rickroll-left-behind';
          rickrollButton.textContent = 'Click Me!';
          rickrollButton.addEventListener('click', function() {
            window.location.href = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
          });
          document.body.appendChild(orbitRing);
          document.body.appendChild(rickrollButton);

          window.requestAnimationFrame(function() {
            orbitRing.classList.add('is-visible');
            rickrollButton.classList.add('is-visible');
            rickrollButton.focus();
          });
        }, 1900);
      }, 300);
    }
  });
})();
