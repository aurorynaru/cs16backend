package main

import (
	"context"
	"crypto/sha256"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestGameAssetCacheInvalidatesSameLengthUpdate(t *testing.T) {
	dir := t.TempDir()
	public := filepath.Join(dir, "public")
	if err := os.Mkdir(public, 0700); err != nil {
		t.Fatal(err)
	}
	writeBundle := func(body string) string {
		t.Helper()
		digest := fmt.Sprintf("%x", sha256.Sum256([]byte(body)))
		if err := os.WriteFile(filepath.Join(public, "gamefiles.zip"), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(public, "gamefiles.sha256"), []byte(digest+"\n"), 0600); err != nil {
			t.Fatal(err)
		}
		return `"` + digest + `"`
	}
	g := newGateway(context.Background(), config{adminToken: testAdminToken, maxPlayers: "2", gameDir: dir}, nil)
	handler := g.handler()
	request := func(method, etag, byteRange string, authorize bool) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, "/cs16/gamefiles.zip", nil)
		if authorize {
			r.Header.Set("Authorization", "Bearer "+testAdminToken)
		}
		r.Header.Set("If-None-Match", etag)
		r.Header.Set("Range", byteRange)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	first := writeBundle("ABCD")
	if response := request("HEAD", "", "", false); response.Code != http.StatusUnauthorized || response.Header().Get("ETag") != "" {
		t.Fatal("unauthenticated request accessed asset metadata")
	}
	head := request("HEAD", "", "", true)
	if head.Code != 200 || head.Header().Get("ETag") != first || head.Header().Get("Content-Length") != "4" || head.Body.Len() != 0 {
		t.Fatal("authenticated HEAD did not expose current bundle identity")
	}
	partial := request("GET", "", "bytes=1-2", true)
	if partial.Code != 206 || partial.Body.String() != "BC" || partial.Header().Get("ETag") != first {
		t.Fatal("range request did not preserve asset bytes and identity")
	}
	if cached := request("GET", first, "", true); cached.Code != 304 || cached.Body.Len() != 0 {
		t.Fatal("current asset validator was not honored")
	}
	second := writeBundle("WXYZ") // Same size as the old bundle.
	changed := request("GET", first, "", true)
	if changed.Code != 200 || changed.Body.String() != "WXYZ" || changed.Header().Get("ETag") != second || first == second {
		t.Fatal("equal-length changed asset remained cached under its old identity")
	}
}
