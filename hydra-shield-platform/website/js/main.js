// ============================================
// Talaix Earth Systems - Main JavaScript
// ============================================

// Navigation scroll effect + mobile hamburger menu.
// When the shared chrome (js/chrome.js, mount #site-header) manages the nav,
// it owns these handlers — main.js skips them to avoid double binding.
const chromeManaged = !!document.getElementById('site-header');

const navbar = document.getElementById('navbar');
if (navbar && !chromeManaged) {
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });
}

const hamburger = document.getElementById('hamburger');
const navLinks = document.getElementById('navLinks');

if (hamburger && navLinks && !chromeManaged) {
    hamburger.addEventListener('click', () => {
        navLinks.classList.toggle('active');
        hamburger.classList.toggle('active');
    });

    // Close menu when clicking a link
    navLinks.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', () => {
            navLinks.classList.remove('active');
            hamburger.classList.remove('active');
        });
    });
}

// Scroll reveal animations
const revealElements = document.querySelectorAll('.reveal');
const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('active');
        }
    });
}, {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
});

revealElements.forEach(el => revealObserver.observe(el));

// Add reveal class to cards on page load
document.addEventListener('DOMContentLoaded', () => {
    const cards = document.querySelectorAll('.problem-card, .app-card, .content-card, .timeline-content');
    cards.forEach((card, index) => {
        card.classList.add('reveal');
        card.style.transitionDelay = `${index * 0.1}s`;
        revealObserver.observe(card);
    });
});

// Contact form handling
// Contact form → POST /api/v2/contact (the real delivery path: the message
// reaches info@talaix.com and the submitter gets an acknowledgement).
// Only when the API cannot be reached do we fall back to a mailto draft.
const contactForm = document.getElementById('contactForm');
if (contactForm) {
    contactForm.addEventListener('submit', (e) => {
        e.preventDefault();
        if (window.HS && HS.track) HS.track('contact_started');

        const name = document.getElementById('name').value;
        const email = document.getElementById('email').value;
        const organization = document.getElementById('organization').value;
        const interest = document.getElementById('interest') ? document.getElementById('interest').value : '';
        const message = document.getElementById('message').value;
        const submitBtn = contactForm.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;

        const apiBase = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
            ? 'http://localhost:8051/api' : '/api';

        function showStatus(kind, text) {
            const el = document.createElement('div');
            el.className = 'notice ' + (kind === 'success' ? 'notice-info' : 'notice-error');
            el.style.marginTop = '12px';
            el.textContent = text;
            contactForm.appendChild(el);
            setTimeout(() => el.remove(), 12000);
        }

        fetch(apiBase + '/v2/contact', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, organization, interest, message })
        }).then((res) => res.json().then((body) => ({ ok: res.ok, body })))
            .then(({ ok, body }) => {
                if (submitBtn) submitBtn.disabled = false;
                if (ok) {
                    showStatus('success', body.message || 'Thank you — your message has been received. We reply by email.');
                    contactForm.reset();
                } else {
                    showStatus('error', body.error || 'Your message could not be sent. Please email info@talaix.com directly.');
                }
            })
            .catch(() => {
                if (submitBtn) submitBtn.disabled = false;
                // Network-level failure: honest fallback — open a mail draft.
                const subject = encodeURIComponent(`Contact from ${name} - ${organization}`);
                const bodyText = encodeURIComponent(`Name: ${name}\nEmail: ${email}\nOrganization: ${organization}\nInterest: ${interest}\n\nMessage:\n${message}`);
                window.location.href = `mailto:info@talaix.com?subject=${subject}&body=${bodyText}`;
                showStatus('error', 'The contact service could not be reached — a mail draft to info@talaix.com was opened instead.');
            });
    });
}

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Add form success style
const style = document.createElement('style');
style.textContent = `
    .form-success {
        background: #10B981;
        color: white;
        padding: 16px;
        border-radius: 8px;
        margin-top: 16px;
        font-size: 0.9rem;
        animation: fadeInUp 0.5s ease-out;
    }
    
    .hamburger.active span:nth-child(1) {
        transform: rotate(45deg) translate(5px, 5px);
    }
    
    .hamburger.active span:nth-child(2) {
        opacity: 0;
    }
    
    .hamburger.active span:nth-child(3) {
        transform: rotate(-45deg) translate(5px, -5px);
    }
`;
document.head.appendChild(style);
