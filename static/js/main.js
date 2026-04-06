window.addEventListener('DOMContentLoaded', () => {
    const flashes = document.querySelectorAll('.flash');
    if (!flashes.length) {
        return;
    }

    setTimeout(() => {
        flashes.forEach((flash) => {
            flash.style.transition = 'opacity .4s ease, transform .4s ease';
            flash.style.opacity = '0';
            flash.style.transform = 'translateY(-4px)';
            setTimeout(() => flash.remove(), 450);
        });
    }, 4200);
});
