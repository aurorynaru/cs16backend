package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMongoosePlayerLaunchHasOnlyScopedExpiringAccess(t *testing.T) {
	dir := t.TempDir()
	public := filepath.Join(dir, "public")
	if err := os.Mkdir(public, 0700); err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]string{"gamefiles.zip": "game-assets-fixture", "gamefiles.sha256": fmt.Sprintf("%x", sha256.Sum256([]byte("game-assets-fixture")))} {
		if err := os.WriteFile(filepath.Join(public, name), []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	origin := "https://mongoose.example"
	brokerToken := strings.Repeat("player-broker-fixture-", 3)
	g := newGateway(context.Background(), config{adminToken: testAdminToken, playerBrokerToken: brokerToken, maxPlayers: "12", mapName: "cs_deathmatch", gameDir: dir, allowedOrigins: map[string]bool{origin: true}}, nil)
	g.endpoint = func(context.Context) (endpoint, error) { return endpoint{Host: "127.0.0.1", Port: 12345}, nil }
	g.ready = func(context.Context) error { return nil }
	clock := time.Now()
	g.assetTickets.now = func() time.Time { return clock }
	handler := g.handler()
	request := func(method, route, authorization, browserOrigin string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, route, nil)
		r.Header.Set("Authorization", authorization)
		r.Header.Set("Origin", browserOrigin)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	if result := request("POST", "/api/player-launch", "", ""); result.Code != 401 {
		t.Fatal("anonymous player access was minted")
	}
	if response := request("GET", "/api/status", "Bearer "+brokerToken, ""); response.Code != 401 {
		t.Fatal("player broker credential authorized admin API")
	}
	if response := request("POST", "/api/session", "Bearer "+brokerToken, ""); response.Code != 401 {
		t.Fatal("player broker credential authorized legacy admin session API")
	}
	result := request("POST", "/api/player-launch", "Bearer "+brokerToken, "")
	if result.Code != 200 || strings.Contains(result.Body.String(), testAdminToken) || strings.Contains(result.Body.String(), brokerToken) {
		t.Fatal("launch failed or exposed permanent credential")
	}
	var launch struct {
		Map, WebSocketPath, GamefilesPath string
		MaxPlayers                        int
		ExpiresInSeconds                  int
	}
	if err := json.Unmarshal(result.Body.Bytes(), &launch); err != nil {
		t.Fatal(err)
	}
	if launch.Map != "cs_deathmatch" || launch.MaxPlayers != 12 || launch.ExpiresInSeconds != 60 {
		t.Fatal("incorrect player launch metadata")
	}
	assetURL, _ := url.Parse(launch.GamefilesPath)
	socketURL, _ := url.Parse(launch.WebSocketPath)
	asset := assetURL.Query().Get("ticket")
	if asset == "" || asset == socketURL.Query().Get("ticket") || g.tickets.valid(asset) {
		t.Fatal("asset access overlaps WebSocket admission")
	}
	for _, method := range []string{"HEAD", "GET", "HEAD"} {
		response := request(method, launch.GamefilesPath, "", origin)
		if response.Code != 200 || response.Header().Get("ETag") == "" || !strings.Contains(response.Header().Get("Access-Control-Expose-Headers"), "ETag") {
			t.Fatal("scoped asset HEAD/GET or cross-origin cache validation failed")
		}
	}
	if response := request("GET", launch.GamefilesPath, "", "https://other.example"); response.Code != 403 {
		t.Fatal("foreign asset origin accepted")
	}
	if response := request("GET", "/api/status", "Bearer "+asset, ""); response.Code != 401 {
		t.Fatal("asset access authorized admin API")
	}
	if response := request("POST", "/api/player-launch", "Bearer "+asset, ""); response.Code != 401 {
		t.Fatal("asset access minted further launches")
	}
	clock = clock.Add(handshakeTimeout)
	if response := request("GET", launch.GamefilesPath, "", origin); response.Code != 401 {
		t.Fatal("expired asset access accepted")
	}
	if !g.tickets.consume(socketURL.Query().Get("ticket")) || g.tickets.consume(socketURL.Query().Get("ticket")) {
		t.Fatal("WebSocket ticket replay behavior changed")
	}
}
