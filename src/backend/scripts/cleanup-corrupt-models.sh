#!/bin/sh
# Remove incomplete or corrupted model caches from the KaggleHub cache directory.
# A model cache is considered corrupt if it contains no recognized weight files
# (model.safetensors, pytorch_model.bin, model_state.pt, head.pt, etc.).
CACHE_ROOT="${KAGGLEHUB_CACHE:-/models}"
MODELS_ROOT="${CACHE_ROOT}/models"

if [ -d "$MODELS_ROOT" ]; then
    find "$MODELS_ROOT" -maxdepth 1 -mindepth 1 -type d | while IFS= read -r model_dir; do
        has_weights="no"
        if find "$model_dir" \
            \( -name "model.safetensors" \
               -o -name "pytorch_model.bin" \
               -o -name "model_state.pt" \
               -o -name "head.pt" \
               -o -name "tf_model.h5" \
               -o -name "model.ckpt.index" \
               -o -name "flax_model.msgpack" \) \
            -type f 2>/dev/null | grep -q .; then
            has_weights="yes"
        fi
        # If an encoder/ subdirectory exists, it must contain base-model
        # weight files. Kaggle publishes these configs with only head.pt and
        # config files; missing encoder weights mean the cache is corrupt.
        encoder_dir="$model_dir/encoder"
        if [ -d "$encoder_dir" ]; then
            if ! find "$encoder_dir" \
                \( -name "model.safetensors" \
                   -o -name "pytorch_model.bin" \
                   -o -name "tf_model.h5" \
                   -o -name "flax_model.msgpack" \
                   -o -name "model.ckpt.index" \) \
                -type f 2>/dev/null | grep -q .; then
                has_weights="no"
            fi
        fi
        if [ "$has_weights" = "no" ]; then
            echo "Removing incomplete model cache: $model_dir"
            rm -rf "$model_dir"
        fi
    done
fi
