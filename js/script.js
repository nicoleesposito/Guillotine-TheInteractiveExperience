function acceptDisclaimer() {
    sessionStorage.setItem('disclaimerAccepted', 'true');
    document.getElementById('disclaimer').style.display = 'none';
}

function init() {
    if (sessionStorage.getItem('disclaimerAccepted') === 'true') {
        const disclaimer = document.getElementById('disclaimer');
        if (disclaimer) disclaimer.style.display = 'none';
    }
}

window.addEventListener('load', init, false);
