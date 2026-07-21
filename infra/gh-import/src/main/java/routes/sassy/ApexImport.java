package routes.sassy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.graphhopper.GraphHopper;
import com.graphhopper.GraphHopperConfig;
import com.graphhopper.jackson.Jackson;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.HashMap;
import java.util.Map;

/**
 * One-shot graph import with the apex_fun encoded value.
 *
 * Usage: java -jar gh-import.jar <config.yml> <scores.csv>
 *
 * Reads the same infra/graphhopper/config.yml the server uses (single source
 * of truth), appends apex_fun to graph.encoded_values programmatically (the
 * stock server must never see apex_fun in its config — it can't import it,
 * only load it from a finished graph), imports, prepares CH+LM, exits.
 */
public class ApexImport {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: gh-import <config.yml> <scores.csv>");
            System.exit(2);
        }

        ObjectMapper yaml = Jackson.initObjectMapper(new ObjectMapper(new YAMLFactory()));
        JsonNode root = yaml.readTree(new File(args[0]));
        GraphHopperConfig config =
                yaml.treeToValue(root.get("graphhopper"), GraphHopperConfig.class);

        String evs = config.getString("graph.encoded_values", "");
        config.putObject("graph.encoded_values", evs + ", " + ApexImportRegistry.KEY);

        Map<Long, Integer> scores = loadScores(args[1]);
        double defaultFun = Double.parseDouble(System.getProperty("apex.fun.default", "0.25"));

        GraphHopper hopper = new GraphHopper();
        hopper.setImportRegistry(new ApexImportRegistry(scores, defaultFun));
        hopper.init(config);
        hopper.importAndClose();
        System.out.println("import complete: " + config.getString("graph.location", "?")
                + " (" + scores.size() + " scored ways)");
    }

    private static Map<Long, Integer> loadScores(String path) throws Exception {
        Map<Long, Integer> scores = new HashMap<>(2_000_000);
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            String line = reader.readLine(); // header
            while ((line = reader.readLine()) != null) {
                int comma = line.indexOf(',');
                if (comma < 1) continue;
                scores.put(Long.parseLong(line.substring(0, comma)),
                        Integer.parseInt(line.substring(comma + 1)));
            }
        }
        return scores;
    }
}
