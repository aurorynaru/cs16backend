package main

import (
	"encoding/hex"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// The immutable image build hashes the complete browser bundle. Its ETag lets
// the existing client invalidate cached assets even if two ZIPs have equal size.
func (g *gateway) gameFiles(w http.ResponseWriter, r *http.Request) {
	publicDir := filepath.Join(g.config.gameDir, "public")
	if data, err := os.ReadFile(filepath.Join(publicDir, "gamefiles.sha256")); err == nil {
		digest := strings.TrimSpace(string(data))
		if decoded, err := hex.DecodeString(digest); err == nil && len(decoded) == 32 {
			w.Header().Set("ETag", `"`+digest+`"`)
		}
	}
	w.Header().Set("Cache-Control", "no-cache")
	http.ServeFile(w, r, filepath.Join(publicDir, "gamefiles.zip"))
}
