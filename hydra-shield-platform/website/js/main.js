// ============================================
// HydraShield Earth Systems - Main JavaScript
// ============================================

// Navigation scroll effect
const navbar = document.getElementById('navbar');
window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
        navbar.classList.add('scrolled');
    } else {
        navbar.classList.remove('scrolled');
    }
});

// Mobile hamburger menu
const hamburger = document.getElementById('hamburger');
const navLinks = document.getElementById('navLinks');

if (hamburger && navLinks) {
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
const contactForm = document.getElementById('contactForm');
if (contactForm) {
    contactForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const name = document.getElementById('name').value;
        const email = document.getElementById('email').value;
        const organization = document.getElementById('organization').value;
        const message = document.getElementById('message').value;
        
        // Build mailto link
        const subject = encodeURIComponent(`Contact from ${name} - ${organization}`);
        const body = encodeURIComponent(`Name: ${name}\nEmail: ${email}\nOrganization: ${organization}\n\nMessage:\n${message}`);
        
        window.location.href = `mailto:info@hydrashield.earth?subject=${subject}&body=${body}`;
        
        // Show success message
        const successMsg = document.createElement('div');
        successMsg.className = 'form-success';
        successMsg.textContent = 'Thank you! Your message has been prepared. Please check your email client to send.';
        contactForm.appendChild(successMsg);
        
        setTimeout(() => {
            successMsg.remove();
            contactForm.reset();
        }, 5000);
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
