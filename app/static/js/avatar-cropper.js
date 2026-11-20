// Cropper.js 2.x: the UMD build exposes its exports on the `Cropper` global.
const AVATAR_CROPPER_TEMPLATE = `
<cropper-canvas>
    <cropper-image translatable scalable></cropper-image>
    <cropper-handle action="move" plain></cropper-handle>
    <cropper-selection aspect-ratio="1" initial-coverage="0.8" movable resizable outlined>
        <cropper-handle action="move" plain></cropper-handle>
        <cropper-handle action="ne-resize"></cropper-handle>
        <cropper-handle action="nw-resize"></cropper-handle>
        <cropper-handle action="se-resize"></cropper-handle>
        <cropper-handle action="sw-resize"></cropper-handle>
    </cropper-selection>
</cropper-canvas>`;

// Keep the selection inside both the canvas and the (movable) image, like
// Cropper.js 1.x viewMode 1 did.
function limitSelectionToImage(cropper) {
    const canvas = cropper.getCropperCanvas();
    const image = cropper.getCropperImage();
    const selection = cropper.getCropperSelection();

    selection.addEventListener('change', (event) => {
        const canvasRect = canvas.getBoundingClientRect();
        const imageRect = image.getBoundingClientRect();
        const left = Math.max(0, imageRect.left - canvasRect.left);
        const top = Math.max(0, imageRect.top - canvasRect.top);
        const right = Math.min(canvasRect.width, imageRect.right - canvasRect.left);
        const bottom = Math.min(canvasRect.height, imageRect.bottom - canvasRect.top);

        const { x, y, width, height } = event.detail;
        if (x >= left && y >= top && x + width <= right && y + height <= bottom) return;

        event.preventDefault();
        // Too big to fit: refuse. Otherwise slide it back against the edge.
        if (width > right - left || height > bottom - top) return;
        const clampedX = Math.min(Math.max(x, left), right - width);
        const clampedY = Math.min(Math.max(y, top), bottom - height);
        selection.$change(clampedX, clampedY, width, height);
    });
}

document.addEventListener('alpine:init', () => {
    Alpine.data('avatarUpload', (initialPreviewSrc) => ({
        isHovering: false,
        previewSrc: initialPreviewSrc,
        cropper: null,
        cropperRun: 0, // bumped per cropper, so stale async setup can bail out
        isCropping: false,

        handleFile(file) {
            if (!file.type.startsWith('image/')) return;
            let reader = new FileReader();
            reader.onload = (e) => {
                this.previewSrc = e.target.result;
                this.isCropping = true;
                // Wait until the crop area is shown and laid out: Cropper sizes the
                // image and selection from the canvas it renders into.
                this.$nextTick(() => requestAnimationFrame(() => this.createCropper()));
            };
            reader.readAsDataURL(file);
        },

        async createCropper() {
            this.destroyCropper();
            const run = this.cropperRun;
            const image = document.getElementById('avatar-preview-img');
            // Keep the raw instance: Alpine returns this.cropper as a reactive proxy
            const cropper = new Cropper.default(image, {
                template: AVATAR_CROPPER_TEMPLATE,
            });
            this.cropper = cropper;

            const cropperImage = cropper.getCropperImage();
            await cropperImage.$ready();
            if (this.cropperRun !== run) return; // replaced or cancelled meanwhile

            // Fit the image, then start with a centred square over 80% of it
            cropperImage.$center('contain');
            const canvasRect = cropper.getCropperCanvas().getBoundingClientRect();
            const imageRect = cropperImage.getBoundingClientRect();
            const size = Math.min(imageRect.width, imageRect.height) * 0.8;
            cropper.getCropperSelection().$change(
                imageRect.left - canvasRect.left + (imageRect.width - size) / 2,
                imageRect.top - canvasRect.top + (imageRect.height - size) / 2,
                size,
                size,
            );
            limitSelectionToImage(cropper);
        },

        destroyCropper() {
            this.cropperRun += 1;
            if (this.cropper) {
                this.cropper.destroy();
                this.cropper = null;
            }
        },

        cancelCrop(originalSrc) {
            this.destroyCropper();
            this.isCropping = false;
            this.previewSrc = originalSrc;
        },

        async uploadAvatar() {
            const btn = document.getElementById('avatar-submit-btn');
            if (!this.cropper) return;

            btn.disabled = true;
            btn.textContent = 'Uploading...';

            try {
                const canvas = await this.cropper.getCropperSelection().$toCanvas({
                    width: 400,
                    height: 400,
                    beforeDraw: (context) => {
                        context.imageSmoothingEnabled = true;
                        context.imageSmoothingQuality = 'high';
                    },
                });
                const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));

                // Idiomatic HTMX: Inject the cropped blob back into the file input
                // using a DataTransfer object, then let HTMX submit the form normally!
                const file = new File([blob], 'avatar.png', { type: 'image/png' });
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);

                this.$refs.fileInput.files = dataTransfer.files;

                // Cleanup cropper UI so the preview shows the cropped image
                this.destroyCropper();
                this.isCropping = false;
                this.previewSrc = URL.createObjectURL(blob);

                // Trigger HTMX natively
                htmx.trigger(this.$refs.form, 'submit');
            } catch (error) {
                console.error('Cropping the avatar failed:', error);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Upload Avatar';
            }
        }
    }));
});
