FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B package

FROM eclipse-temurin:21-jre
COPY --from=build /build/target/gh-import.jar /gh-import.jar
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /gh-import.jar \"$@\"", "--"]
