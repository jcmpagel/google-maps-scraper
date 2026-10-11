package gmaps_test

import (
	"encoding/csv"
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/gosom/google-maps-scraper/gmaps"
)

func removalPayload(t *testing.T, text string) []any {
	t.Helper()

	data := make([]any, 242)
	data[11] = "Test restaurant"
	data[13] = []any{"Restaurant"}

	if text != "" {
		data[241] = []any{[]any{[]any{3, []any{text}}}}
	}

	return data
}

func detailEntry(t *testing.T, data []any) gmaps.Entry {
	t.Helper()

	payload := make([]any, 7)
	payload[6] = data
	raw, err := json.Marshal(payload)
	require.NoError(t, err)

	entry, err := gmaps.EntryFromJSON(raw)
	require.NoError(t, err)

	return entry
}

func searchEntry(t *testing.T, data []any) *gmaps.Entry {
	t.Helper()

	item := make([]any, 15)
	item[14] = data
	raw, err := json.Marshal([]any{[]any{nil, []any{nil, item}}})
	require.NoError(t, err)

	entries, err := gmaps.ParseSearchResults(raw)
	require.NoError(t, err)
	require.Len(t, entries, 1)

	return entries[0]
}

func TestReviewRemovalRanges(t *testing.T) {
	t.Parallel()

	cases := []struct {
		text string
		min  int
		max  int
	}{
		{"One review was removed", 1, 1},
		{"Eine Bewertung wurde entfernt", 1, 1},
		{"Two to five reviews were removed", 2, 5},
		{"Zwei bis fünf Bewertungen wurden entfernt", 2, 5},
		{"Zwei bis fuenf Rezensionen wurden entfernt", 2, 5},
		{"Six to ten reviews were removed", 6, 10},
		{"Sechs bis zehn Bewertungen wurden entfernt", 6, 10},
		{"Eleven to twenty reviews were removed", 11, 20},
		{"Twenty-one to fifty reviews removed", 21, 50},
		{"Twenty one to fifty reviews removed", 21, 50},
		{"Elf bis zwanzig Bewertungen entfernt", 11, 20},
		{"201–250 reviews removed", 201, 250},
		{"201—250 reviews removed", 201, 250},
		{"201 − 250 reviews removed", 201, 250},
		{"201\u00a0to\u00a0250 reviews removed", 201, 250},
		{"1,001 to 1,250 reviews removed", 1001, 1250},
		{"1.001 bis 1.250 Bewertungen entfernt", 1001, 1250},
		{"Over 250 reviews removed", 251, 0},
		{"More than 250 reviews removed", 251, 0},
		{"Above 250 reviews removed", 251, 0},
		{"Über 250 Bewertungen entfernt", 251, 0},
		{"Ueber 250 Bewertungen entfernt", 251, 0},
		{"Mehr als 250 Bewertungen entfernt", 251, 0},
		{"250 to 201 reviews removed", 0, 0},
		{"250 to 1 review removed", 0, 0},
		{"0 to 5 reviews removed", 0, 0},
		{"0 to 1 review removed", 0, 0},
		{"201 to 250 photos removed", 0, 0},
		{"An unfamiliar notice", 0, 0},
	}

	for _, bounds := range [][2]int{{2, 5}, {6, 10}, {11, 20}, {21, 50}, {51, 100}, {101, 150}, {151, 200}, {201, 250}, {251, 500}} {
		for _, separator := range []string{" to ", " bis ", "-"} {
			cases = append(cases, struct {
				text string
				min  int
				max  int
			}{strconv.Itoa(bounds[0]) + separator + strconv.Itoa(bounds[1]) + " reviews removed", bounds[0], bounds[1]})
		}
	}

	for _, tc := range cases {
		t.Run(tc.text, func(t *testing.T) {
			t.Parallel()

			data := removalPayload(t, tc.text)
			entry := detailEntry(t, data)
			search := searchEntry(t, data)
			require.Equal(t, tc.min, entry.RemovedReviewsMin)
			require.Equal(t, tc.max, entry.RemovedReviewsMax)
			require.Equal(t, entry.RemovedReviewsMin, search.RemovedReviewsMin)
			require.Equal(t, entry.RemovedReviewsMax, search.RemovedReviewsMax)
			require.Equal(t, tc.text, entry.RemovedReviewsNotice)

			if tc.min == 0 {
				require.Equal(t, gmaps.RemovalNoticeUnrecognized, entry.RemovedReviewsStatus)
			} else {
				require.Equal(t, gmaps.RemovalNoticeParsed, entry.RemovedReviewsStatus)
			}

			require.Equal(t, entry.RemovedReviewsStatus, search.RemovedReviewsStatus)
		})
	}
}

func TestReviewRemovalLiveGermanFixture(t *testing.T) {
	t.Parallel()

	raw, err := os.ReadFile("../testdata/review_removal_la_casa_de.json")
	require.NoError(t, err)

	entry, err := gmaps.EntryFromJSON(raw)
	require.NoError(t, err)
	require.Equal(t, "La Casa de Kebab", entry.Title)
	require.Equal(t, 2, entry.RemovedReviewsMin)
	require.Equal(t, 5, entry.RemovedReviewsMax)
	require.Equal(t, gmaps.RemovalNoticeParsed, entry.RemovedReviewsStatus)
	require.Contains(t, entry.RemovedReviewsNotice, "zwei bis fünf")
	require.False(t, entry.ReviewCountAvailable)
	require.False(t, entry.ReviewsPerRatingAvailable)
}

func TestReviewMetricAvailability(t *testing.T) {
	t.Parallel()

	data := removalPayload(t, "")
	missing := detailEntry(t, data)
	require.False(t, missing.ReviewCountAvailable)
	require.False(t, missing.ReviewsPerRatingAvailable)
	require.Equal(t, gmaps.RemovalNoticeNotPresent, missing.RemovedReviewsStatus)

	metrics := make([]any, 9)
	metrics[8] = 0
	data[4] = metrics
	ratings := make([]any, 4)
	ratings[3] = []any{0, 0, 0, 0, 0}
	data[175] = ratings

	for _, entry := range []gmaps.Entry{detailEntry(t, data), *searchEntry(t, data)} {
		require.True(t, entry.ReviewCountAvailable)
		require.True(t, entry.ReviewsPerRatingAvailable)
		require.Zero(t, entry.ReviewCount)
	}

	metrics[8] = 1.5
	ratings[3] = []any{0, nil, 0, 0, 0}
	partial := detailEntry(t, data)
	require.False(t, partial.ReviewCountAvailable)
	require.False(t, partial.ReviewsPerRatingAvailable)
}

func TestReviewNoticeSelectionAndCSV(t *testing.T) {
	t.Parallel()

	data := removalPayload(t, "")
	data[241] = []any{[]any{
		[]any{1, []any{"Posting is disabled"}},
		[]any{5, []any{"Previous posts are hidden"}},
	}}
	entry := detailEntry(t, data)
	require.Equal(t, gmaps.RemovalNoticeNotPresent, entry.RemovedReviewsStatus)

	data[241] = []any{[]any{
		[]any{3, []any{"Unrecognized removal notice"}},
		[]any{3, []any{"Unrecognized long text", nil, nil, "Zwei bis fünf Bewertungen entfernt"}},
		[]any{3, []any{"201 to 250 reviews removed"}},
	}}
	entry = detailEntry(t, data)
	require.Equal(t, 2, entry.RemovedReviewsMin)
	require.Equal(t, 5, entry.RemovedReviewsMax)
	require.Equal(t, "Zwei bis fünf Bewertungen entfernt", entry.RemovedReviewsNotice)

	raw, err := json.Marshal(entry)
	require.NoError(t, err)

	var fields map[string]any

	require.NoError(t, json.Unmarshal(raw, &fields))
	require.Equal(t, gmaps.RemovalNoticeParsed, fields["removed_reviews_status"])
	require.Equal(t, false, fields["review_count_available"])

	var output strings.Builder
	writer := csv.NewWriter(&output)
	require.NoError(t, writer.WriteAll([][]string{entry.CsvHeaders(), entry.CsvRow()}))

	rows, err := csv.NewReader(strings.NewReader(output.String())).ReadAll()
	require.NoError(t, err)
	require.Len(t, rows, 2)
	require.Len(t, rows[1], len(rows[0]))

	columns := make(map[string]string, len(rows[0]))
	for i, header := range rows[0] {
		columns[header] = rows[1][i]
	}

	require.Equal(t, "2", columns["removed_reviews_min"])
	require.Equal(t, "5", columns["removed_reviews_max"])
	require.Equal(t, gmaps.RemovalNoticeParsed, columns["removed_reviews_status"])
	require.Equal(t, entry.RemovedReviewsNotice, columns["removed_reviews_notice"])
	require.Equal(t, "false", columns["review_count_available"])
	require.Equal(t, "false", columns["reviews_per_rating_available"])
}
