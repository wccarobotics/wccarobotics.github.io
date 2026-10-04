// FTC qualification-match stats: OPR / DPR / CCWM, ranking points, schedule difficulty,
// predictions for the rest of the qualification schedule, and projected final rankings.
//
// Usage:
//   dotnet run FtcStats.cs -- <season> <eventCode> [options]
//   dotnet run FtcStats.cs -- https://ftc-events.firstinspires.org/2026/USMISAS [options]
//
// Options:
//   --through N     Only treat qual matches 1..N as played (simulate a tournament in progress)
//   --shrink X      Ridge regularization toward the average team (0 = classic OPR). Default is
//                   0.5 while qual matches remain and 0 once quals are complete.
//   --sims N        Number of Monte Carlo simulations for rank projections (default 20000)
//   --markdown      Print markdown tables instead of aligned text
//   --save DIR      Save the raw API responses to DIR
//   --load DIR      Read raw API responses from DIR instead of calling the API
//
// Credentials: ftc-api-credentials.json ({"username": "...", "auth_key": "..."}) found in the
// current directory or any parent, or FTC_API_USERNAME / FTC_API_KEY environment variables.

#:property PublishAot=false

using System.Globalization;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;

var opts = Options.Parse(args);
if (opts is null)
{
    Console.Error.WriteLine("Usage: dotnet run FtcStats.cs -- <season> <eventCode> | <ftc-events URL> [--through N] [--shrink X] [--sims N] [--markdown] [--save DIR] [--load DIR]");
    return 1;
}

var source = new DataSource(opts);
var schedule = (await source.Get("schedule", $"schedule/{opts.EventCode}?tournamentLevel=qual"))["schedule"]!.AsArray();
var results = (await source.Get("matches", $"matches/{opts.EventCode}?tournamentLevel=qual"))["matches"]!.AsArray();
JsonArray? scores = null;
try
{
    // Detailed score breakdowns carry the bonus ranking point flags.
    scores = (await source.Get("scores", $"scores/{opts.EventCode}/qual"))["matchScores"]?.AsArray();
}
catch (Exception ex)
{
    Console.Error.WriteLine($"Warning: couldn't load score details, so bonus ranking points are unavailable ({ex.Message})");
}
JsonArray? rankings = opts.Through is null
    ? (await source.Get("rankings", $"rankings/{opts.EventCode}"))["rankings"]?.AsArray()
    : null;

var full = Tournament.Build(schedule, results, scores, null);
var evt = opts.Through is null ? full : Tournament.Build(schedule, results, scores, opts.Through);
if (evt.Matches.Count == 0)
{
    Console.Error.WriteLine($"No qualification schedule found for {opts.Season} {opts.EventCode}.");
    return 1;
}

// Shrinkage helps predict the rest of the schedule; once quals are over, classic OPR is the
// standard number and matches what other stats sites report.
double shrink = opts.Shrink ?? (evt.Remaining.Any() ? 0.5 : 0);
var model = Model.Fit(evt, shrink);
var official = rankings?.ToDictionary(r => (int)r!["teamNumber"]!, r => (Rank: (int)r!["rank"]!, AvgRp: (double)r["sortOrder1"]!)) ?? new();

new Report(evt, full, model, official, opts).Print();
return 0;

// ---------------------------------------------------------------------------

record Options(int Season, string EventCode, int? Through, double? Shrink, int Sims, bool Markdown, string? SaveDir, string? LoadDir)
{
    public static Options? Parse(string[] args)
    {
        var positional = new List<string>();
        int? through = null; double? shrink = null; int sims = 20000; bool md = false; string? save = null, load = null;
        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--through": through = int.Parse(args[++i]); break;
                case "--shrink": shrink = double.Parse(args[++i], CultureInfo.InvariantCulture); break;
                case "--sims": sims = int.Parse(args[++i]); break;
                case "--markdown": md = true; break;
                case "--save": save = args[++i]; break;
                case "--load": load = args[++i]; break;
                default: positional.Add(args[i]); break;
            }
        }

        // Accept an FTC Events URL like https://ftc-events.firstinspires.org/2026/USMISAS/...
        if (positional.Count == 1 && Uri.TryCreate(positional[0], UriKind.Absolute, out var uri))
            positional = uri.AbsolutePath.Split('/', StringSplitOptions.RemoveEmptyEntries).Take(2).ToList();

        if (positional.Count != 2 || !int.TryParse(positional[0], out int season)) return null;
        return new Options(season, positional[1].ToUpperInvariant(), through, shrink, sims, md, save, load);
    }
}

class DataSource(Options opts)
{
    HttpClient? _http;

    public async Task<JsonNode> Get(string name, string path)
    {
        string fileName = $"{opts.Season}-{opts.EventCode}-{name}.json";
        string json;
        if (opts.LoadDir is not null)
        {
            json = await File.ReadAllTextAsync(Path.Combine(opts.LoadDir, fileName));
        }
        else
        {
            _http ??= CreateClient();
            var resp = await _http.GetAsync($"https://ftc-api.firstinspires.org/v2.0/{opts.Season}/{path}");
            json = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
                throw new Exception($"FTC API {path} returned {(int)resp.StatusCode}: {json}");
        }
        if (opts.SaveDir is not null)
        {
            Directory.CreateDirectory(opts.SaveDir);
            await File.WriteAllTextAsync(Path.Combine(opts.SaveDir, fileName), json);
        }
        return JsonNode.Parse(json)!;
    }

    static HttpClient CreateClient()
    {
        string? user = Environment.GetEnvironmentVariable("FTC_API_USERNAME");
        string? key = Environment.GetEnvironmentVariable("FTC_API_KEY");
        if (user is null || key is null)
        {
            for (var dir = new DirectoryInfo(Environment.CurrentDirectory); dir is not null; dir = dir.Parent)
            {
                string path = Path.Combine(dir.FullName, "ftc-api-credentials.json");
                if (!File.Exists(path)) continue;
                var creds = JsonNode.Parse(File.ReadAllText(path))!;
                user = (string?)creds["username"];
                key = (string?)creds["auth_key"];
                break;
            }
        }
        if (user is null || key is null)
            throw new Exception("FTC API credentials not found (ftc-api-credentials.json or FTC_API_USERNAME/FTC_API_KEY).");

        var http = new HttpClient();
        http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue(
            "Basic", Convert.ToBase64String(Encoding.UTF8.GetBytes($"{user}:{key}")));
        return http;
    }
}

// ---------------------------------------------------------------------------

record Slot(int Team, bool Surrogate, bool Dq);

// NpScore: score without the foul points the opponents gave away (the ranking tiebreaker).
// Bonuses: bonus ranking point flags from the score details (null if not available).
record Alliance(List<Slot> Slots, int? Score, int? Auto, int? NpScore, Dictionary<string, bool>? Bonuses)
{
    public IEnumerable<int> Teams => Slots.Select(s => s.Team);
}

record Match(int Number, Alliance Red, Alliance Blue)
{
    public bool Played => Red.Score is not null && Blue.Score is not null;
    public IEnumerable<Alliance> Alliances => [Red, Blue];
    public Alliance Opponent(Alliance a) => a == Red ? Blue : Red;
    public Alliance? AllianceOf(int team) => Red.Teams.Contains(team) ? Red : Blue.Teams.Contains(team) ? Blue : null;
}

record Tournament(List<Match> Matches, List<int> Teams, Dictionary<int, string> Names, List<string> BonusNames)
{
    public IEnumerable<Match> Played => Matches.Where(m => m.Played);
    public IEnumerable<Match> Remaining => Matches.Where(m => !m.Played);

    public static Tournament Build(JsonArray schedule, JsonArray results, JsonArray? scores, int? through)
    {
        var resultsByNumber = results
            .Where(r => r!["postResultTime"] is not null && r["scoreRedFinal"] is not null)
            .ToDictionary(r => (int)r!["matchNumber"]!);

        // Bonus RPs are the boolean "...RP" fields of each alliance's score details, which lets
        // this work for any season's game without hardcoding names.
        var bonusNames = new List<string>();
        var details = new Dictionary<(int, string), Dictionary<string, bool>>();
        foreach (var ms in scores ?? [])
        {
            foreach (var a in ms!["alliances"]!.AsArray())
            {
                var flags = a!.AsObject()
                    .Where(kv => kv.Key.EndsWith("RP") && kv.Value?.GetValueKind() is JsonValueKind.True or JsonValueKind.False)
                    .ToDictionary(kv => kv.Key, kv => (bool)kv.Value!);
                foreach (var name in flags.Keys)
                    if (!bonusNames.Contains(name)) bonusNames.Add(name);
                details[((int)ms["matchNumber"]!, (string)a["alliance"]!)] = flags;
            }
        }
        var names = new Dictionary<int, string>();
        var matches = new List<Match>();

        foreach (var s in schedule)
        {
            int number = (int)s!["matchNumber"]!;
            var result = through is null || number <= through ? resultsByNumber.GetValueOrDefault(number) : null;
            var dqs = result?["teams"]!.AsArray()
                .Where(t => (bool?)t!["dq"] == true).Select(t => (int)t!["teamNumber"]!).ToHashSet() ?? [];

            Alliance MakeAlliance(string color)
            {
                var slots = s["teams"]!.AsArray()
                    .Where(t => ((string)t!["station"]!).StartsWith(color))
                    .OrderBy(t => (string)t!["station"]!)
                    .Select(t =>
                    {
                        int team = (int)t!["teamNumber"]!;
                        names[team] = ((string?)t["teamName"] ?? "").Trim();
                        return new Slot(team, (bool?)t["surrogate"] == true, dqs.Contains(team));
                    })
                    .ToList();
                // score{Color}Foul is the foul points that alliance committed, which go to the other alliance.
                string other = color == "Red" ? "Blue" : "Red";
                return new Alliance(slots,
                    (int?)result?[$"score{color}Final"], (int?)result?[$"score{color}Auto"],
                    (int?)result?[$"score{color}Final"] - ((int?)result?[$"score{other}Foul"] ?? 0),
                    result is null ? null : details.GetValueOrDefault((number, color)));
            }

            matches.Add(new Match(number, MakeAlliance("Red"), MakeAlliance("Blue")));
        }

        matches.Sort((a, b) => a.Number.CompareTo(b.Number));
        var teams = names.Keys.Order().ToList();
        return new Tournament(matches, teams, names, bonusNames);
    }
}

// ---------------------------------------------------------------------------

// Least-squares component ratings. Each played alliance contributes one equation
// "sum of the alliance's team ratings = observed value". A ridge term pulls each team
// toward the average team, which keeps the system solvable (and less noisy) when only a
// few matches have been played.
class Model
{
    public required Dictionary<int, double> Opr, NpOpr, AutoOpr, Dpr, Ccwm;
    // Per bonus RP: each team's contribution to the chance its alliance earns that bonus.
    public required Dictionary<string, Dictionary<int, double>> Bonus;
    public required double MeanOpr, Shrink;
    public double MarginSigma;
    public required int Observations;

    public static Model Fit(Tournament evt, double shrink)
    {
        var index = evt.Teams.Select((t, i) => (t, i)).ToDictionary(x => x.t, x => x.i);
        int n = evt.Teams.Count;
        var rows = evt.Played.SelectMany(m => m.Alliances.Select(a => (m, a))).ToList();
        int perAlliance = evt.Matches.Max(m => m.Red.Slots.Count);

        double ridge = Math.Max(shrink, 1e-6);

        // Solves (A^T A + ridge * I) x = A^T b + ridge * prior, using only alliances where
        // `value` is known (score details can lag behind results).
        Dictionary<int, double> Solve(Func<Match, Alliance, double?> value)
        {
            var data = rows.Select(r => (r.a, v: value(r.m, r.a))).Where(x => x.v is not null).ToList();
            double prior = data.Count == 0 ? 0 : data.Average(x => x.v!.Value) / perAlliance;
            var ata = new double[n, n];
            var rhs = new double[n];
            foreach (var (a, v) in data)
            {
                foreach (int t1 in a.Teams)
                {
                    rhs[index[t1]] += v!.Value;
                    foreach (int t2 in a.Teams) ata[index[t1], index[t2]] += 1;
                }
            }
            for (int i = 0; i < n; i++)
            {
                ata[i, i] += ridge;
                rhs[i] += ridge * prior;
            }
            var x = LinearAlgebra.SolveSpd(ata, rhs);
            return evt.Teams.ToDictionary(t => t, t => x[index[t]]);
        }

        var opr = Solve((m, a) => a.Score!.Value);
        var model = new Model
        {
            Opr = opr,
            NpOpr = Solve((m, a) => a.NpScore),
            AutoOpr = Solve((m, a) => a.Auto ?? 0),
            Dpr = Solve((m, a) => m.Opponent(a).Score!.Value),
            Ccwm = Solve((m, a) => a.Score!.Value - m.Opponent(a).Score!.Value),
            Bonus = evt.BonusNames.ToDictionary(b => b, b => Solve((m, a) => a.Bonuses is null ? null : a.Bonuses.GetValueOrDefault(b) ? 1 : 0)),
            MeanOpr = opr.Values.Average(),
            Shrink = shrink,
            Observations = rows.Count,
        };

        // Spread of actual match margins around predicted margins, used for win probabilities.
        // Residuals on the training data understate the true error, so correct for the number
        // of fitted parameters, and fall back to a guess when there is too little data.
        double fallback = Math.Max(10, model.MeanOpr * perAlliance * 0.5);
        var played = evt.Played.ToList();
        if (played.Count >= 3)
        {
            double ss = played.Sum(m => Math.Pow((m.Red.Score!.Value - m.Blue.Score!.Value) - model.PredictMargin(m), 2));
            double dof = Math.Max(played.Count - n / 2.0, played.Count / 4.0);
            double sigma = Math.Sqrt(ss / dof);
            // Blend toward the fallback while data is thin.
            double w = Math.Min(1, played.Count / (double)n);
            model.MarginSigma = w * sigma + (1 - w) * Math.Max(sigma, fallback);
        }
        else
        {
            model.MarginSigma = fallback;
        }
        return model;
    }

    public double Predict(Alliance a) => a.Teams.Sum(t => Opr[t]);
    public double PredictNp(Alliance a) => a.Teams.Sum(t => NpOpr[t]);
    public double BonusProbability(Alliance a, string bonus) => Math.Clamp(a.Teams.Sum(t => Bonus[bonus][t]), 0, 1);

    // Expected ranking points for an alliance in an unplayed match.
    public double ExpectedRp(Match m, Alliance a)
    {
        double pRed = RedWinProbability(m);
        double pWin = a == m.Red ? pRed : 1 - pRed;
        return Rp.Win * pWin + Bonus.Keys.Sum(b => BonusProbability(a, b));
    }
    public double PredictMargin(Match m) => Predict(m.Red) - Predict(m.Blue);
    public double RedWinProbability(Match m) => Stats.NormalCdf(PredictMargin(m) / MarginSigma);

    public double WinProbability(Match m, int team)
    {
        double p = RedWinProbability(m);
        return m.Red.Teams.Contains(team) ? p : 1 - p;
    }

    // Win probability for a hypothetical average team placed in `team`'s slot.
    public double AverageTeamWinProbability(Match m, int team)
    {
        var mine = m.AllianceOf(team)!;
        double myScore = MeanOpr + mine.Teams.Where(t => t != team).Sum(t => Opr[t]);
        double margin = myScore - Predict(m.Opponent(mine));
        return Stats.NormalCdf(margin / MarginSigma);
    }
}

static class Rp
{
    // RP per match: 3 for a win, 1 for a tie, plus 1 per bonus earned. Ranking is by average
    // RP, then average pre-foul score. (Verified against the official 2026 rankings.)
    public const int Win = 3, Tie = 1;

    public static int ForAlliance(Match m, Alliance a)
    {
        int score = a.Score!.Value, opp = m.Opponent(a).Score!.Value;
        return (score > opp ? Win : score == opp ? Tie : 0) + (a.Bonuses?.Count(b => b.Value) ?? 0);
    }

    // Playoff alliance count by number of teams (competition manual table 13-2).
    public static int AllianceCount(int teams) => teams <= 10 ? 2 : teams <= 20 ? 4 : teams <= 40 ? 6 : 8;
}

// Ranking-point standings. Surrogate appearances don't count, and a disqualified team gets
// 0 RP for the match.
class Standings
{
    public required Dictionary<int, double> RpTotal, NpTotal;
    public required Dictionary<int, int> Counted;
    public required List<int> Order;

    public double AvgRp(int t) => Counted[t] == 0 ? 0 : RpTotal[t] / Counted[t];
    public double AvgNp(int t) => Counted[t] == 0 ? 0 : NpTotal[t] / Counted[t];
    public int Rank(int t) => Order.IndexOf(t) + 1;

    public static Standings Compute(Tournament evt)
    {
        var rp = evt.Teams.ToDictionary(t => t, _ => 0.0);
        var np = evt.Teams.ToDictionary(t => t, _ => 0.0);
        var counted = evt.Teams.ToDictionary(t => t, _ => 0);
        foreach (var m in evt.Played)
        {
            foreach (var a in m.Alliances)
            {
                int allianceRp = Rp.ForAlliance(m, a);
                foreach (var slot in a.Slots.Where(s => !s.Surrogate))
                {
                    rp[slot.Team] += slot.Dq ? 0 : allianceRp;
                    np[slot.Team] += a.NpScore!.Value;
                    counted[slot.Team]++;
                }
            }
        }
        return Create(evt.Teams, rp, np, counted);
    }

    public static Standings Create(List<int> teams, Dictionary<int, double> rp, Dictionary<int, double> np, Dictionary<int, int> counted)
    {
        double Avg(Dictionary<int, double> d, int t) => counted[t] == 0 ? 0 : d[t] / counted[t];
        var order = teams.OrderByDescending(t => Avg(rp, t)).ThenByDescending(t => Avg(np, t)).ThenBy(t => t).ToList();
        return new Standings { RpTotal = rp, NpTotal = np, Counted = counted, Order = order };
    }
}

// Monte Carlo projection of the final qualification rankings: plays out every remaining match
// many times, drawing scores from each alliance's OPR prediction plus normal noise and each
// bonus RP from its predicted probability.
class RankProjection
{
    public required Dictionary<int, double> MeanRank, MeanAvgRp;
    public required Dictionary<int, int[]> RankCounts; // RankCounts[t][r - 1] = sims where t finished rank r
    public required int Sims;

    public double ProbabilityTop(int t, int k) => RankCounts[t].Take(k).Sum() / (double)Sims;

    public int Percentile(int t, double p)
    {
        int target = (int)Math.Ceiling(p * Sims), cumulative = 0;
        for (int r = 0; r < RankCounts[t].Length; r++)
            if ((cumulative += RankCounts[t][r]) >= target) return r + 1;
        return RankCounts[t].Length;
    }

    public static RankProjection Run(Tournament evt, Model model, Standings current, int sims)
    {
        var rng = new Random(12345);
        var remaining = evt.Remaining.Select(m => m.Alliances.Select(a => (
            Teams: a.Slots.Where(s => !s.Surrogate).Select(s => s.Team).ToArray(),
            Pred: model.Predict(a),
            NpPred: model.PredictNp(a),
            Bonus: evt.BonusNames.Select(b => model.BonusProbability(a, b)).ToArray())).ToArray()).ToList();
        double sigma = model.MarginSigma / Math.Sqrt(2); // per-alliance score noise

        var rankSum = evt.Teams.ToDictionary(t => t, _ => 0.0);
        var rpSum = evt.Teams.ToDictionary(t => t, _ => 0.0);
        var counts = evt.Teams.ToDictionary(t => t, _ => new int[evt.Teams.Count]);
        var rp = new Dictionary<int, double>(current.RpTotal);
        var np = new Dictionary<int, double>(current.NpTotal);
        var counted = new Dictionary<int, int>(current.Counted);

        for (int s = 0; s < sims; s++)
        {
            foreach (int t in evt.Teams)
            {
                rp[t] = current.RpTotal[t];
                np[t] = current.NpTotal[t];
                counted[t] = current.Counted[t];
            }
            foreach (var alliances in remaining)
            {
                double[] z = [Gaussian(rng), Gaussian(rng)];
                double[] score = [alliances[0].Pred + sigma * z[0], alliances[1].Pred + sigma * z[1]];
                for (int i = 0; i < 2; i++)
                {
                    var a = alliances[i];
                    double allianceRp = score[i] > score[1 - i] ? Rp.Win : 0;
                    foreach (double p in a.Bonus)
                        if (rng.NextDouble() < p) allianceRp++;
                    foreach (int t in a.Teams)
                    {
                        rp[t] += allianceRp;
                        np[t] += a.NpPred + sigma * z[i];
                        counted[t]++;
                    }
                }
            }
            var final = Standings.Create(evt.Teams, rp, np, counted);
            for (int r = 0; r < final.Order.Count; r++)
            {
                int t = final.Order[r];
                rankSum[t] += r + 1;
                counts[t][r]++;
                rpSum[t] += final.AvgRp(t);
            }
        }

        return new RankProjection
        {
            MeanRank = rankSum.ToDictionary(kv => kv.Key, kv => kv.Value / sims),
            MeanAvgRp = rpSum.ToDictionary(kv => kv.Key, kv => kv.Value / sims),
            RankCounts = counts,
            Sims = sims,
        };
    }

    static double Gaussian(Random rng) =>
        Math.Sqrt(-2 * Math.Log(1 - rng.NextDouble())) * Math.Cos(2 * Math.PI * rng.NextDouble());
}


static class LinearAlgebra
{
    // Cholesky solve for a symmetric positive-definite system.
    public static double[] SolveSpd(double[,] a, double[] b)
    {
        int n = b.Length;
        var l = new double[n, n];
        for (int i = 0; i < n; i++)
        {
            for (int j = 0; j <= i; j++)
            {
                double sum = a[i, j];
                for (int k = 0; k < j; k++) sum -= l[i, k] * l[j, k];
                l[i, j] = i == j ? Math.Sqrt(Math.Max(sum, 1e-12)) : sum / l[j, j];
            }
        }
        var y = new double[n];
        for (int i = 0; i < n; i++)
        {
            double sum = b[i];
            for (int k = 0; k < i; k++) sum -= l[i, k] * y[k];
            y[i] = sum / l[i, i];
        }
        var x = new double[n];
        for (int i = n - 1; i >= 0; i--)
        {
            double sum = y[i];
            for (int k = i + 1; k < n; k++) sum -= l[k, i] * x[k];
            x[i] = sum / l[i, i];
        }
        return x;
    }
}

static class Stats
{
    public static double NormalCdf(double z) => 0.5 * (1 + Erf(z / Math.Sqrt(2)));

    // Abramowitz & Stegun 7.1.26 (max error 1.5e-7).
    static double Erf(double x)
    {
        double sign = Math.Sign(x);
        x = Math.Abs(x);
        double t = 1 / (1 + 0.3275911 * x);
        double y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.Exp(-x * x);
        return sign * y;
    }
}

// ---------------------------------------------------------------------------

record TeamLine(int Team)
{
    public int Wins, Losses, Ties, Played, Remaining;
    public double TotalScore, ExpectedWins, AvgTeamWinsAll, AvgTeamWinsPlayed, AvgTeamWinsRemaining, ProjectedWins;
    public double PartnerOpr, OpponentOpr;
    public int ScheduledMatches;
}

class Report(Tournament evt, Tournament full, Model model, Dictionary<int, (int Rank, double AvgRp)> official, Options opts)
{
    readonly Dictionary<int, TeamLine> _lines = Compute(evt, model);
    readonly Dictionary<int, Match> _actual = full.Matches.ToDictionary(m => m.Number);
    readonly Standings _standings = Standings.Compute(evt);
    readonly RankProjection? _projection = evt.Remaining.Any() ? RankProjection.Run(evt, model, Standings.Compute(evt), opts.Sims) : null;
    readonly int _captains = Rp.AllianceCount(evt.Teams.Count);

    static Dictionary<int, TeamLine> Compute(Tournament evt, Model model)
    {
        var lines = evt.Teams.ToDictionary(t => t, t => new TeamLine(t));
        foreach (var m in evt.Matches)
        {
            foreach (var a in m.Alliances)
            {
                var opp = m.Opponent(a);
                foreach (var slot in a.Slots)
                {
                    var line = lines[slot.Team];
                    line.ScheduledMatches++;
                    line.PartnerOpr += a.Teams.Where(t => t != slot.Team).Sum(t => model.Opr[t]);
                    line.OpponentOpr += opp.Teams.Sum(t => model.Opr[t]);
                    double avgWin = model.AverageTeamWinProbability(m, slot.Team);
                    line.AvgTeamWinsAll += avgWin;

                    if (slot.Surrogate) continue; // surrogate matches don't count toward a team's record
                    if (m.Played)
                    {
                        line.Played++;
                        line.TotalScore += a.Score!.Value;
                        line.AvgTeamWinsPlayed += avgWin;
                        line.ExpectedWins += model.WinProbability(m, slot.Team);
                        if (slot.Dq || a.Score < opp.Score) line.Losses++;
                        else if (a.Score > opp.Score) line.Wins++;
                        else line.Ties++;
                    }
                    else
                    {
                        line.Remaining++;
                        line.AvgTeamWinsRemaining += avgWin;
                        line.ProjectedWins += model.WinProbability(m, slot.Team);
                    }
                }
            }
        }
        foreach (var l in lines.Values)
        {
            l.ProjectedWins += l.Wins + l.Ties * 0.5;
            if (l.ScheduledMatches > 0)
            {
                l.PartnerOpr /= l.ScheduledMatches;
                l.OpponentOpr /= l.ScheduledMatches;
            }
        }
        return lines;
    }

    string Name(int team)
    {
        string name = evt.Names.GetValueOrDefault(team, "");
        return name.Length > 24 ? name[..23] + "…" : name;
    }

    string Teams(Alliance a) => string.Join(" ", a.Teams);

    static string F(double v, int digits = 1) => v.ToString("F" + digits);
    static string Pct(double v) => v > 0 && v < 0.005 ? "<1%" : v < 1 && v > 0.995 ? ">99%" : (v * 100).ToString("F0") + "%";

    // "swarmRP" -> "Swarm%"
    static string BonusLabel(string name) => char.ToUpperInvariant(name[0]) + name[1..^2] + "%";

    // Fraction of a team's counted matches (with score details) where its alliance earned the bonus.
    string BonusRate(int team, string bonus)
    {
        var flags = evt.Played
            .Select(m => m.Alliances.FirstOrDefault(a => a.Slots.Any(s => s.Team == team && !s.Surrogate)))
            .Where(a => a?.Bonuses is not null)
            .Select(a => a!.Bonuses!.GetValueOrDefault(bonus))
            .ToList();
        return flags.Count == 0 ? "—" : Pct(flags.Count(f => f) / (double)flags.Count);
    }

    public void Print()
    {
        var played = evt.Played.ToList();
        var remaining = evt.Remaining.ToList();

        Heading($"FTC {opts.Season} {opts.EventCode} — qualification stats", 1);
        Console.WriteLine($"Qualification matches played: {played.Count} of {evt.Matches.Count}" +
                          (opts.Through is not null ? $" (simulated through match {opts.Through})" : ""));
        Console.WriteLine($"Teams: {evt.Teams.Count}   Playoff alliances: {_captains}   Average OPR: {F(model.MeanOpr)}   " +
                          $"Match margin σ: {F(model.MarginSigma)}   Shrink: {model.Shrink}" +
                          (opts.Shrink is null ? (remaining.Count > 0 ? " (default while matches remain)" : " (default once quals are complete)") : ""));
        if (played.Count == 0)
            Console.WriteLine("No matches played yet — every team is rated as the average team.");
        int missingDetails = played.Sum(m => m.Alliances.Count(a => a.Bonuses is null));
        if (missingDetails > 0)
            Console.WriteLine($"Warning: score details missing for {missingDetails} played alliance(s); their bonus RPs aren't counted.");

        PrintRankings();
        PrintTeamStats();
        PrintSchedule(remaining.Count > 0);
        if (remaining.Count > 0) PrintPredictions(remaining);
        if (opts.Through is not null) PrintPredictionCheck(remaining);

        Heading("Glossary", 2);
        if (opts.Markdown) Console.WriteLine("```text");
        Console.WriteLine("""
            RP     Average ranking points per match (3 per win, 1 per tie, +1 per bonus earned)
            Tiebreak  Average alliance score not counting foul points from opponents (breaks RP ties)
            Bonus% Share of the team's matches where its alliance earned that bonus RP
            Proj RP / Proj rank   Average final RP and rank across simulations of the remaining matches
            Range  Middle 80% of simulated final ranks (10th to 90th percentile)
            Top N  Chance of finishing in the top N (the alliance captain spots), and of finishing #1
            OPR    Offensive Power Rating: least-squares estimate of points each team adds to its alliance score
            npOPR  OPR computed from scores with opponent fouls removed
            Auto   OPR computed from autonomous points only
            DPR    Points the team's opponents score (lower is better defense/luck)
            CCWM   Calculated contribution to winning margin
            xW     Expected wins in played matches given everyone's OPR; Luck = actual wins − xW
            Partner/Opp OPR   Average partner OPR and average opposing-alliance OPR total, over the full qual schedule
            Avg-team win%     Win rate a perfectly average team would expect in this team's slots
                              (lower = harder schedule); split into played and remaining matches
            Proj W  Current wins (ties = ½) plus win probability in remaining matches
            """);
        if (opts.Markdown) Console.WriteLine("```");
        Console.WriteLine();
        Console.WriteLine("Match data provided by the FIRST Tech Challenge Events API (https://ftc-events.firstinspires.org/services/API).");
    }

    void PrintRankings()
    {
        Heading(_projection is null ? "Rankings" : "Rankings and projections", 2);
        var header = new List<string> { "Rank", "Team", "Name", "W-L-T", "RP", "Tiebreak" };
        header.AddRange(evt.BonusNames.Select(BonusLabel));
        if (_projection is not null) header.AddRange(["Proj RP", "Proj rank", "Range", $"Top {_captains}", "#1"]);

        var rows = new List<string[]>();
        foreach (int t in _standings.Order)
        {
            var l = _lines[t];
            var row = new List<string>
            {
                _standings.Rank(t).ToString(), t.ToString(), Name(t), $"{l.Wins}-{l.Losses}-{l.Ties}",
                F(_standings.AvgRp(t), 2), F(_standings.AvgNp(t)),
            };
            row.AddRange(evt.BonusNames.Select(b => BonusRate(t, b)));
            if (_projection is not null)
            {
                row.AddRange([
                    F(_projection.MeanAvgRp[t], 2), F(_projection.MeanRank[t]),
                    $"{_projection.Percentile(t, 0.1)}–{_projection.Percentile(t, 0.9)}",
                    Pct(_projection.ProbabilityTop(t, _captains)), Pct(_projection.ProbabilityTop(t, 1)),
                ]);
            }
            rows.Add(row.ToArray());
        }
        Table(header.ToArray(), rows, leftAligned: ["Name", "Range"]);

        // Sanity check the RP rules against the official rankings when we have them.
        if (official.Count > 0)
        {
            var mismatched = _standings.Order
                .Where(t => !official.TryGetValue(t, out var o) || o.Rank != _standings.Rank(t) || Math.Abs(o.AvgRp - _standings.AvgRp(t)) > 0.005)
                .ToList();
            Console.WriteLine();
            Console.WriteLine(mismatched.Count == 0
                ? "Computed rankings match the official rankings."
                : "Warning: computed rankings differ from the official rankings for " +
                  string.Join(", ", mismatched.Select(t => official.TryGetValue(t, out var o)
                      ? $"{t} (official #{o.Rank}, {o.AvgRp:F2} RP)" : $"{t} (not ranked)")));
        }
    }

    void PrintTeamStats()
    {
        Heading("Team ratings", 2);
        var header = new List<string> { "#", "Team", "Name", "W-L-T", "OPR", "npOPR", "Auto", "DPR", "CCWM", "Avg Score", "xW", "Luck" };

        var rows = new List<string[]>();
        int i = 0;
        foreach (var l in _lines.Values.OrderByDescending(l => model.Opr[l.Team]))
        {
            var row = new List<string>
            {
                (++i).ToString(), l.Team.ToString(), Name(l.Team), $"{l.Wins}-{l.Losses}-{l.Ties}",
                F(model.Opr[l.Team]), F(model.NpOpr[l.Team]), F(model.AutoOpr[l.Team]),
                F(model.Dpr[l.Team]), F(model.Ccwm[l.Team]),
                l.Played > 0 ? F(l.TotalScore / l.Played) : "—",
                F(l.ExpectedWins), (l.Wins + l.Ties * 0.5 - l.ExpectedWins).ToString("+0.0;-0.0;0.0"),
            };
            rows.Add(row.ToArray());
        }
        Table(header.ToArray(), rows, leftAligned: ["Name"]);
    }

    void PrintSchedule(bool hasRemaining)
    {
        Heading("Schedule difficulty (hardest first)", 2);
        var header = new List<string> { "#", "Team", "Name", "Partner OPR", "Opp OPR", "Avg-team win%" };
        if (hasRemaining) header.AddRange(["Played", "Remaining", "Proj W"]);

        var rows = new List<string[]>();
        int i = 0;
        foreach (var l in _lines.Values.OrderBy(l => l.AvgTeamWinsAll / Math.Max(1, l.ScheduledMatches)))
        {
            var row = new List<string>
            {
                (++i).ToString(), l.Team.ToString(), Name(l.Team), F(l.PartnerOpr), F(l.OpponentOpr),
                Pct(l.AvgTeamWinsAll / Math.Max(1, l.ScheduledMatches)),
            };
            if (hasRemaining)
            {
                row.Add(l.Played > 0 ? Pct(l.AvgTeamWinsPlayed / l.Played) : "—");
                row.Add(l.Remaining > 0 ? $"{Pct(l.AvgTeamWinsRemaining / l.Remaining)} ({l.Remaining})" : "—");
                row.Add(F(l.ProjectedWins));
            }
            rows.Add(row.ToArray());
        }
        Table(header.ToArray(), rows, leftAligned: ["Name"]);
    }

    void PrintPredictions(List<Match> remaining)
    {
        Heading("Predictions for remaining matches", 2);
        var rows = remaining.Select(m =>
        {
            double p = model.RedWinProbability(m);
            return new[]
            {
                $"Q{m.Number}", Teams(m.Red), F(model.Predict(m.Red), 0), F(model.Predict(m.Blue), 0), Teams(m.Blue),
                p >= 0.5 ? $"Red {Pct(p)}" : $"Blue {Pct(1 - p)}",
                F(model.ExpectedRp(m, m.Red)), F(model.ExpectedRp(m, m.Blue)),
                ActualResult(m),
            };
        }).ToList();
        string[] header = ["Match", "Red", "Red pred", "Blue pred", "Blue", "Favorite", "Red xRP", "Blue xRP", "Actual"];
        bool showActual = rows.Any(r => r[^1] != "");
        if (!showActual)
        {
            header = header[..^1];
            rows = rows.Select(r => r[..^1]).ToList();
        }
        Table(header, rows, leftAligned: ["Red", "Blue", "Favorite", "Actual"]);
    }

    string ActualResult(Match m)
    {
        var a = _actual[m.Number];
        if (!a.Played) return "";
        int r = a.Red.Score!.Value, b = a.Blue.Score!.Value;
        return $"{r}-{b} " + (r > b ? "Red" : r < b ? "Blue" : "Tie");
    }

    // When simulating with --through, compare predictions with what actually happened.
    void PrintPredictionCheck(List<Match> remaining)
    {
        var checkable = remaining.Select(m => (pred: m, actual: _actual[m.Number])).Where(x => x.actual.Played).ToList();
        if (checkable.Count == 0) return;

        Heading($"Prediction check (matches {opts.Through + 1}+ vs actual results)", 2);
        int decided = 0, correct = 0;
        double brier = 0, scoreError = 0;
        foreach (var (pred, actual) in checkable)
        {
            int margin = actual.Red.Score!.Value - actual.Blue.Score!.Value;
            double p = model.RedWinProbability(pred);
            brier += Math.Pow(p - (margin > 0 ? 1 : margin < 0 ? 0 : 0.5), 2);
            scoreError += Math.Abs(model.Predict(pred.Red) - actual.Red.Score.Value) + Math.Abs(model.Predict(pred.Blue) - actual.Blue.Score.Value);
            if (margin == 0) continue;
            decided++;
            if ((p >= 0.5) == (margin > 0)) correct++;
        }
        Console.WriteLine($"Winner predicted correctly: {correct} of {decided} ({Pct(correct / (double)Math.Max(1, decided))})");
        Console.WriteLine($"Brier score: {brier / checkable.Count:F3} (0.25 = coin flip, lower is better)");
        Console.WriteLine($"Mean absolute alliance score error: {scoreError / (2 * checkable.Count):F1} points");

        // Projected vs actual final wins.
        var fullLines = Compute(full, model);
        double winError = _lines.Values.Average(l =>
            Math.Abs(l.ProjectedWins - (fullLines[l.Team].Wins + fullLines[l.Team].Ties * 0.5)));
        Console.WriteLine($"Mean absolute error of projected final wins: {winError:F2}");

        if (_projection is null) return;
        var final = Standings.Compute(full);
        double rankError = evt.Teams.Average(t => Math.Abs(_projection.MeanRank[t] - final.Rank(t)));
        int inRange = evt.Teams.Count(t => final.Rank(t) >= _projection.Percentile(t, 0.1) && final.Rank(t) <= _projection.Percentile(t, 0.9));
        var projectedTop = evt.Teams.OrderBy(t => _projection.MeanRank[t]).Take(_captains).ToHashSet();
        int topHits = final.Order.Take(_captains).Count(projectedTop.Contains);
        double rankBrier = evt.Teams.Average(t => Math.Pow(_projection.ProbabilityTop(t, _captains) - (final.Rank(t) <= _captains ? 1 : 0), 2));
        Console.WriteLine($"Mean absolute error of projected final rank: {rankError:F1}");
        Console.WriteLine($"Final rank inside projected range: {inRange} of {evt.Teams.Count} teams (range is meant to cover ~80%)");
        Console.WriteLine($"Projected top {_captains} that finished top {_captains}: {topHits} of {_captains}   Top-{_captains} Brier: {rankBrier:F3}");
    }

    void Heading(string text, int level)
    {
        Console.WriteLine();
        if (opts.Markdown) Console.WriteLine(new string('#', level) + " " + text);
        else
        {
            Console.WriteLine(text);
            Console.WriteLine(new string(level == 1 ? '=' : '-', text.Length));
        }
        Console.WriteLine();
    }

    void Table(string[] header, List<string[]> rows, string[] leftAligned)
    {
        var left = header.Select(h => leftAligned.Contains(h) || h == "Team").ToArray();
        if (opts.Markdown)
        {
            Console.WriteLine("| " + string.Join(" | ", header) + " |");
            Console.WriteLine("|" + string.Join("|", left.Select(l => l ? "---" : "---:")) + "|");
            foreach (var r in rows) Console.WriteLine("| " + string.Join(" | ", r) + " |");
            return;
        }
        var widths = header.Select((h, i) => Math.Max(h.Length, rows.Count == 0 ? 0 : rows.Max(r => r[i].Length))).ToArray();
        string Line(string[] cells) => string.Join("  ", cells.Select((c, i) => left[i] ? c.PadRight(widths[i]) : c.PadLeft(widths[i]))).TrimEnd();
        Console.WriteLine(Line(header));
        Console.WriteLine(string.Join("  ", widths.Select(w => new string('-', w))));
        foreach (var r in rows) Console.WriteLine(Line(r));
    }
}
