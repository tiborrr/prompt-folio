document.addEventListener('alpine:init', () => {
    Alpine.data('avatarUpload', (initialPreviewSrc) => ({
        isHovering: false,
        previewSrc: initialPreviewSrc,
        cropper: null,
        isCropping: false,
        
        handleFile(file) {
            if (!file.type.startsWith('image/')) return;
            let reader = new FileReader();
            reader.onload = (e) => {
                this.previewSrc = e.target.result;
                this.isCropping = true;
                this.$nextTick(() => {
                    if (this.cropper) { this.cropper.destroy(); }
                    const image = document.getElementById('avatar-preview-img');
                    this.cropper = new Cropper(image, {
                        aspectRatio: 1,
                        viewMode: 1,
                        dragMode: 'move',
                        guides: false,
                        center: false,
                        highlight: false,
                        background: false,
                        cropBoxMovable: true,
                        cropBoxResizable: true,
                    });
                });
            };
            reader.readAsDataURL(file);
        },
        
        uploadAvatar() {
            const btn = document.getElementById('avatar-submit-btn');
            if (!this.cropper) return;
            
            btn.disabled = true;
            btn.textContent = 'Uploading...';
            
            this.cropper.getCroppedCanvas({
                width: 400,
                height: 400,
                imageSmoothingEnabled: true,
                imageSmoothingQuality: 'high',
            }).toBlob((blob) => {
                // Idiomatic HTMX: Inject the cropped blob back into the file input 
                // using a DataTransfer object, then let HTMX submit the form normally!
                const file = new File([blob], 'avatar.png', { type: 'image/png' });
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);
                
                this.$refs.fileInput.files = dataTransfer.files;
                
                // Cleanup cropper UI so the preview shows the cropped image
                this.cropper.destroy();
                this.cropper = null;
                this.isCropping = false;
                this.previewSrc = URL.createObjectURL(blob);
                
                // Trigger HTMX natively
                htmx.trigger(this.$refs.form, 'submit');
                
                btn.disabled = false;
                btn.textContent = 'Upload Avatar';
            }, 'image/png');
        }
    }));
});
