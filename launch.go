package main

import (
	"net/http"
	"net/url"
	"strconv"
)

func (g *gateway) authorizedPlayerBroker(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !authorized(r, g.config.playerBrokerToken) {
			writeJSON(w, 401, map[string]string{"error": "trusted player broker authorization required"})
			return
		}
		next(w, r)
	}
}

// Only a trusted server-side broker (Infor API Gateway for Mongoose) may mint
// these scoped grants. The permanent admin credential never goes to the WUC.
func (g *gateway) playerLaunch(w http.ResponseWriter, r *http.Request) {
	if _, err := g.endpoint(r.Context()); err != nil {
		writeJSON(w, 503, map[string]string{"error": err.Error()})
		return
	}
	if err := g.ready(r.Context()); err != nil {
		writeJSON(w, 503, map[string]string{"error": err.Error()})
		return
	}
	socketTicket, err := g.tickets.issue()
	if err != nil {
		writeJSON(w, 429, map[string]string{"error": err.Error()})
		return
	}
	assetTicket, err := g.assetTickets.issue()
	if err != nil {
		g.tickets.consume(socketTicket)
		writeJSON(w, 429, map[string]string{"error": err.Error()})
		return
	}
	maxPlayers, _ := strconv.Atoi(g.config.maxPlayers)
	writeJSON(w, 200, map[string]any{
		"map": g.config.mapName, "maxPlayers": maxPlayers,
		"websocketPath":    "/cs16/dust2/websocket?ticket=" + url.QueryEscape(socketTicket),
		"gamefilesPath":    "/player/gamefiles.zip?ticket=" + url.QueryEscape(assetTicket),
		"expiresInSeconds": int(handshakeTimeout.Seconds()),
	})
}

func (g *gateway) playerGameFiles(w http.ResponseWriter, r *http.Request) {
	if !g.originAllowed(r) {
		writeJSON(w, 403, map[string]string{"error": "player asset origin rejected"})
		return
	}
	if !g.assetTickets.valid(r.URL.Query().Get("ticket")) {
		writeJSON(w, 401, map[string]string{"error": "player asset access expired; request a fresh launch through Mongoose"})
		return
	}
	g.gameFiles(w, r)
}
