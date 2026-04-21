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

function initUpload() {
    const input     = document.getElementById('photo-input');
    const preview   = document.getElementById('preview');
    const uploadBtn = document.getElementById('upload-btn');
    const progWrap  = document.getElementById('progress-bar-wrap');
    const progBar   = document.getElementById('progress-bar');
    const status    = document.getElementById('upload-status');

    let pendingFile = null;

    input.addEventListener('change', () => {
        const file = input.files[0];
        if (!file) return;
        pendingFile = file;
        preview.src = URL.createObjectURL(file);
        preview.style.display = 'block';
        uploadBtn.style.display = 'inline-block';
        uploadBtn.disabled = false;
        status.textContent = '';
        progBar.style.width = '0%';
    });

    uploadBtn.addEventListener('click', () => {
        if (!pendingFile) return;

        const formData = new FormData();
        formData.append('file', pendingFile);
        formData.append('upload_preset', cloudinaryConfig.uploadPreset);
        formData.append('folder', 'guillotine');

        const xhr = new XMLHttpRequest();
        xhr.open('POST', `https://api.cloudinary.com/v1_1/${cloudinaryConfig.cloudName}/image/upload`);

        xhr.upload.onprogress = e => {
            if (e.lengthComputable) {
                progBar.style.width = (e.loaded / e.total * 100) + '%';
            }
        };

        xhr.onload = () => {
            if (xhr.status === 200) {
                progBar.style.width = '100%';
                setTimeout(() => {
                    status.textContent = 'Submitted. The blade awaits.';
                    uploadBtn.style.display = 'none';
                    progWrap.style.display = 'none';
                    pendingFile = null;
                }, 300);
            } else {
                status.textContent = 'Upload failed. Please try again.';
                uploadBtn.disabled = false;
                progWrap.style.display = 'none';
            }
        };

        xhr.onerror = () => {
            status.textContent = 'Network error. Please try again.';
            uploadBtn.disabled = false;
            progWrap.style.display = 'none';
        };

        uploadBtn.disabled = true;
        progWrap.style.display = 'block';
        status.textContent = 'Uploading…';
        xhr.send(formData);
    });
}

window.addEventListener('load', () => {
    init();
    initUpload();
});
